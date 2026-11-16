"""Qwen3-Omni-Flash answering through the Alibaba Singapore API.

Answer flow (each step can end the question; see docs/answer-flow.md):
  1. Greetings/thanks, instruction overrides and live-task requests are handled locally.
  2. Local BM25 retrieval over the whole approved FAQ. An exact FAQ match is rendered locally from
     the approved text with its stored links. A bare ambiguous question gets a local clarification.
  3. If Qwen is disabled (questions not approved for external processing) or has no key, no request
     is sent: GAB questions go to a person, unrelated ones get a redirect.
  4. Otherwise Qwen gets the rules, the best-matching complete FAQ entries (with their required
     exceptions) and the question, and returns JSON that grounding.py validates: a grounded
     explanation, labelled general guidance, a clarification, a hand-off or "need more".
  5. "Need more" (or no local match) allows ONE targeted retrieval retry. With still no FAQ entry, a
     GAB-relevant question may get general guidance only (no entries means no GAB policy).
Every request goes through the shared provider quota (RPM/TPM across workers), bounded retries and
a per-question call budget; per-user quotas are applied by GuardedEngine before this runs.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import ssl
import threading
import time
from contextlib import contextmanager, nullcontext

import httpx

from .config import QWEN_MODEL
from .contracts import Answer
from .conversation import assert_no_tools
from .grounding import (
    SOURCE_SELECTION_RULES,
    UNRELATED,
    NeedMoreEvidence,
    grounded_answer,
    render_sources,
)
from .model_context import (
    EvidenceConflict,
    NoEvidence,
    PromptTooLong,
    bounded_history,
    entry_context,
    estimated_input_tokens,
    pack_entries,
    request_bytes,
)
from .model_limits import PROVIDER_BUSY, ModelLimits
from .policy import (
    INSTRUCTION_REPLY,
    LIVE_TASK_REPLY,
    is_instruction_override,
    is_live_task_help,
)
from .provider_quota import SharedProviderQuota
from .redact import clean_untrusted, scrub_mentions
from .retrieval import LocalRetriever, is_gab_question, targeted_query

log = logging.getLogger(__name__)
ENDPOINT = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = QWEN_MODEL
# Reasoning is discarded, bounded separately from the final JSON reply.
MAX_REASONING_BYTES = 16384
REQUEST_DEADLINE = 35
ERROR_MESSAGE = "I couldn't complete the FAQ lookup. A team member can help with this question."
BUSY_MESSAGE = "The FAQ assistant is very busy right now. Please ask again in about a minute."
DISABLED_MESSAGE = "I can't interpret this question automatically yet, so a team member will help."
NOT_ESTABLISHED = (
    "I couldn't establish this from the current GAB sources after a targeted search. "
    "A team member can help."
)
NO_ENTRIES_NOTE = (
    "(No current FAQ entry matched. Do not state GAB policy: give labelled general guidance, ask "
    "a clarification, or use needs_human. No further search is available.)"
)
# The provider-slot wait plus the 35 s request deadline fits the 45 s adapter deadline.
PACING_WAIT = 10.0
# Kept for configuration compatibility: Qwen no longer replaces a decline with an embedding match.
BACKSTOP_OUTCOMES = frozenset({"not_in_faq", "error"})

VIDEO_QUESTION = (
    "Which topic do you need the video for: account setup, natural conversations, debug and JSON "
    "export, artefacts, reset, ratings, final preference, or sharing the conversation?"
)
RATING_QUESTION = "Do you mean the 1-5 L1 dimension ratings or the side-by-side (SxS) preference?"
ACCOUNT_QUESTION = "Which tool is the account for: Gemini, ChatGPT, Gmail or Drive?"
# Bare questions that cannot be answered without one more detail. Asked locally, never escalated.
LOCAL_CLARIFICATIONS = {
    "which model": "Is this about Product A or Product B?",
    "what model": "Is this about Product A or Product B?",
    "which file": "Which file or submission step do you mean?",
    "what file": "Which file or submission step do you mean?",
    "which video": VIDEO_QUESTION,
    "what video": VIDEO_QUESTION,
    "video link": VIDEO_QUESTION,
    "which tutorial": VIDEO_QUESTION,
    "which account": ACCOUNT_QUESTION,
    "what account": ACCOUNT_QUESTION,
    "which rating": RATING_QUESTION,
    "what rating": RATING_QUESTION,
    "which score": RATING_QUESTION,
    "what score": RATING_QUESTION,
}
FILLER_WORDS = frozenset({"and", "so", "ok", "okay", "but", "then", "the", "a", "um", "hmm"})


DANGLING_RE = re.compile(r"\b(?:it|that|this|one|them|those|these)\b", re.IGNORECASE)
DANGLING_QUESTION = (
    "Could you say which step, file or tool you mean? For example: the debug JSON, the "
    "conversation link, an artefact, or the environment reset."
)


def local_clarification(question: str) -> str | None:
    """A focused question for a bare question that cannot be placed without context."""
    words = [w for w in re.findall(r"[a-z]+", (question or "").lower()) if w not in FILLER_WORDS]
    if " ".join(words) in LOCAL_CLARIFICATIONS:
        return LOCAL_CLARIFICATIONS[" ".join(words)]
    # Seen live: "which one do I use?", "where do i upload it", "is it mandatory?" got a guessed
    # topic. A pronoun with at most two content words and no history cannot be placed safely.
    from .search import words as content_words

    if (
        DANGLING_RE.search(question or "")
        and len(content_words(question or "")) <= 2
        and not is_gab_question(question)  # "how do I reset it" names its topic
    ):
        return DANGLING_QUESTION
    return None


def parse_selection(text: str):
    """The model's JSON object. Tolerates a Markdown code fence around it, nothing else."""
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


class ProviderCapacity(ValueError):
    def __init__(self, attempted=False):
        self.attempted = attempted


class ProviderGate:
    """Process-wide cap on provider requests per rolling minute.

    Alibaba rate-limits the whole account, and a rejected request would otherwise become an
    "error" answer: a staff card and DMs for a question nobody got wrong. Waiting is bounded; when
    no slot opens in time the question is turned away without contacting the provider.
    """

    def __init__(self, per_minute, clock=time.monotonic, sleep=time.sleep):
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self._starts = collections.deque()
        self._lock = threading.Lock()

    def acquire(self, max_wait=PACING_WAIT) -> bool:
        deadline = self.clock() + max_wait
        while True:
            with self._lock:
                now = self.clock()
                while self._starts and self._starts[0] <= now - 60:
                    self._starts.popleft()
                if len(self._starts) < self.per_minute:
                    self._starts.append(now)
                    return True
                wait = self._starts[0] + 60 - now
            if now + wait > deadline:
                return False
            self.sleep(wait)


class Qwen:
    def __init__(
        self,
        knowledge,
        *,
        model=MODEL,
        limits=None,
        max_history_messages=4,
        client=None,
        gate=None,
        backstop=None,
        quota_path=None,
        external_questions_approved=False,
        external_history_approved=False,
        enable_thinking=False,
        local_answers=True,
        sleep=time.sleep,
    ):
        if model != MODEL:
            raise ValueError(f"Qwen requires model {MODEL!r}")
        self.knowledge = knowledge
        self.model = model
        self.limits = limits or ModelLimits()
        self.gate = gate or SharedProviderQuota(self.limits, quota_path)
        self.external_questions_approved = external_questions_approved
        self.external_history_approved = external_history_approved
        if type(enable_thinking) is not bool:
            raise ValueError("enable_thinking must be true or false")
        self.enable_thinking = enable_thinking
        self.local_answers = local_answers
        self.sleep = sleep
        # Retained attribute: the embedding backstop is no longer consulted by Qwen (see
        # docs/answer-flow.md, "local_backstop"). engine.py never passes one.
        self.search = backstop
        self.max_history_messages = min(max_history_messages, 4)
        # An injected client stays caller-owned; default clients close after each call.
        self.client = client

    # --- request -----------------------------------------------------------------------------

    def build_request(
        self, question, role="unknown", history=None, retrieval_query=None, allow_empty=False
    ):
        """(request, entries). The request is the complete outbound payload: see
        docs/outbound-payload.md. Nothing else is sent to the provider."""
        question = clean_untrusted(scrub_mentions(question)).strip()
        local_history = bounded_history(history, self.max_history_messages, self.limits)
        sent_history = (
            [m for m in local_history if not is_instruction_override(m["content"])]
            if self.external_history_approved
            else []
        )

        def make_request(entries, history_messages):
            system = (
                SOURCE_SELECTION_RULES
                + "<faq>\n"
                + (entry_context(entries) if entries else NO_ENTRIES_NOTE)
                + "\n</faq>"
            )
            return assert_no_tools(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        *history_messages,
                        {
                            "role": "user",
                            "content": f"<asker_role>{role}</asker_role>\n<question>{question}</question>",
                        },
                    ],
                    "max_tokens": self.limits.max_output_tokens,
                    "temperature": 0,  # the same question should select the same entries
                    "enable_thinking": self.enable_thinking,
                    "modalities": ["text"],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            )

        return pack_entries(
            self.knowledge,
            role,
            question,
            local_history,
            self.limits,
            make_request,
            retrieval_query,
            sent_history=sent_history,
            allow_empty=allow_empty,
        )

    # --- answer flow ---------------------------------------------------------------------------

    def answer(self, question, role="unknown", history=None):
        from .search import GREETING_REPLY, THANKS_REPLY, THANKS_WORDS, WORD_RE, is_small_talk

        question = question or ""
        if is_small_talk(question):
            return Answer(
                THANKS_REPLY
                if set(WORD_RE.findall(question.lower())) & THANKS_WORDS
                else GREETING_REPLY,
                "small_talk",
                via="local: greeting",
            )
        if is_instruction_override(question):
            return Answer(INSTRUCTION_REPLY, "declined", via="qwen: instruction override")
        if is_live_task_help(question):
            return Answer(LIVE_TASK_REPLY, "declined", via="qwen: live task help")
        from .introduction import introduction

        intro = introduction(question, self.knowledge, role)
        if intro is not None:
            return intro
        unavailable = self._model_unavailable()
        evidence = None
        if self.local_answers:
            try:
                evidence = LocalRetriever(self.knowledge).retrieve(
                    question, role, history, self.limits.retrieval_candidates
                )
            except Exception:
                log.exception("FAQ retrieval failed")
                return Answer(ERROR_MESSAGE, "error", via="retrieval: reload failure")
            if evidence.problem:
                return Answer(
                    "The current sources need review before I can answer this. A team member can help.",
                    "needs_human",
                    escalation_reason=evidence.problem,
                    via="retrieval: conflict",
                )
            if evidence.exact and evidence.candidates:
                return render_sources(
                    [c.entry for c in evidence.candidates],
                    [evidence.candidates[0].entry.id],
                    "answered",
                    via="retrieval: exact",
                )
            clarification = local_clarification(question)
            if clarification and (not history or unavailable):
                return Answer(clarification, "clarification", via="retrieval: clarification")
        if unavailable:
            return self._without_model(question, role, history, evidence, *unavailable)

        state = {"calls": 0, "sent": False}
        query = None
        for attempt in range(2):  # the first pass, then ONE targeted retrieval retry
            try:
                result = self._select(question, role, history, state, retrieval_query=query)
            except NeedMoreEvidence as more:
                if attempt:
                    break
                # A local miss retries with the question's subject words found in FAQ titles; an
                # empty retry query (nothing FAQ-like, e.g. "a good pasta recipe") sends nothing.
                query = clean_untrusted(more.query or self._retry_query(question, role, history))
                query = query[:180]
                if not query and not more.from_model:
                    break
                continue
            if (
                not attempt
                and result.outcome == "unrelated"
                and result.via == "qwen"
                and is_gab_question(question, history)
            ):
                # Observed live: entries matched on a side word ("link" -> sharing entries) and
                # Qwen called a GAB question unrelated. Use the retry before accepting that.
                query = clean_untrusted(self._retry_query(question, role, history))[:180]
                if query:
                    continue
            return result
        if not state["sent"] and is_gab_question(question, history, broad=True):
            # No FAQ entry matched even after the targeted search. Qwen may still give clearly
            # labelled general guidance; without entries it cannot state GAB policy (grounding.py).
            try:
                return self._select(
                    question, role, history, state, retrieval_query=query, allow_empty=True
                )
            except NeedMoreEvidence:
                pass
        if state["sent"] or is_gab_question(question, history):
            return Answer(
                NOT_ESTABLISHED,
                "needs_human",
                escalation_reason="not in the current FAQ after a targeted search",
                via="retrieval: unavailable",
            )
        return Answer(UNRELATED, "unrelated", via="retrieval: unrelated")

    def _retry_query(self, question, role, history):
        try:
            return LocalRetriever(self.knowledge).targeted_query(question, role, history)
        except Exception:
            log.exception("Targeted retry query failed")
            return targeted_query(question, history)

    def _model_unavailable(self):
        """(reply, escalation reason, outcome) when no request may be sent, else None."""
        if not self.external_questions_approved:
            return (
                DISABLED_MESSAGE,
                "Qwen disabled: external processing of questions is not approved",
                "needs_human",
            )
        if not os.environ.get("DASHSCOPE_API_KEY", "").strip():
            return (
                "The model API key is not configured. Please contact the team.",
                "Qwen unavailable: DASHSCOPE_API_KEY is not set",
                "error",
            )
        return None

    def _without_model(self, question, role, history, evidence, text, reason, outcome):
        """Qwen is off: GAB questions go to a person, unrelated ones get a redirect (no staff)."""
        if evidence is None:
            try:
                evidence = LocalRetriever(self.knowledge).retrieve(
                    question, role, history, self.limits.retrieval_candidates
                )
            except Exception:
                log.exception("FAQ retrieval failed while Qwen is unavailable")
        relevant = bool(evidence is not None and evidence.candidates) or is_gab_question(
            question, history
        )
        if not relevant:
            return Answer(UNRELATED, "unrelated", via="local: unrelated (Qwen unavailable)")
        return Answer(text, outcome, escalation_reason=reason, via="qwen: unavailable")

    # --- provider ------------------------------------------------------------------------------

    @contextmanager
    def _response(self, request, key, state):
        started = time.monotonic()
        for attempt in range(self.limits.provider_max_retries + 1):
            if state.get("calls", 0) >= self.limits.provider_calls_per_question:
                raise ValueError("Per-question provider call budget exhausted")
            reservation = (
                self.gate.reserve(
                    estimated_input_tokens(request)
                    + self.limits.max_output_tokens
                    + ((MAX_REASONING_BYTES + 2) // 3 if self.enable_thinking else 0)
                )
                if hasattr(self.gate, "reserve")
                else self.gate.acquire()
            )
            if not reservation:
                raise ProviderCapacity(attempt > 0 or state.get("sent", False))
            state["calls"] = state.get("calls", 0) + 1
            status = "transport_error"
            delay = None
            try:
                client_context = (
                    nullcontext(self.client)
                    if self.client is not None
                    else httpx.Client(verify=ssl.create_default_context())
                )
                remaining = REQUEST_DEADLINE - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValueError("Request deadline exceeded")
                state["sent"] = True
                with (
                    client_context as client,
                    client.stream(
                        "POST",
                        ENDPOINT,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        content=request_bytes(request),
                        timeout=httpx.Timeout(min(10, remaining), connect=min(5, remaining)),
                        follow_redirects=False,
                    ) as response,
                ):
                    status = str(response.status_code)
                    if (
                        response.status_code in {429, 502, 503, 504}
                        and attempt < self.limits.provider_max_retries
                    ):
                        try:
                            hint = float(response.headers.get("Retry-After", "0"))
                        except ValueError:
                            hint = 0
                        if hint > 3:
                            raise ValueError("Provider Retry-After exceeds bounded waiting")
                        delay = min(3, max(hint, self.limits.provider_backoff_seconds * 2**attempt))
                    else:
                        yield response
                        return
            finally:
                if hasattr(self.gate, "finish"):
                    self.gate.finish(reservation, state.get("usage"), status)
            if delay is not None:
                if time.monotonic() - started + delay >= REQUEST_DEADLINE:
                    raise ValueError("Retry deadline exceeded")
                self.sleep(delay)

    def _select(
        self,
        question,
        role="unknown",
        history=None,
        state=None,
        retrieval_query=None,
        allow_empty=False,
    ):
        state = {"calls": 0, "sent": False} if state is None else state
        try:
            request, entries = self.build_request(
                question, role, history, retrieval_query, allow_empty=allow_empty
            )
        except PromptTooLong as error:
            return Answer(str(error), "limited", via="qwen: prompt limit")
        except NoEvidence:
            raise NeedMoreEvidence(
                self._retry_query(question, role, history), from_model=False
            ) from None
        except EvidenceConflict as error:
            return Answer(
                "The current FAQ sources need review. A team member can help.",
                "needs_human",
                escalation_reason=str(error),
                via="retrieval: conflict",
            )
        except Exception:
            log.exception("Qwen FAQ context could not be prepared")
            return Answer(ERROR_MESSAGE, "error", via="qwen")
        if not self.external_questions_approved or any(
            not e.external_processing_approved for e in entries
        ):
            return Answer(
                DISABLED_MESSAGE,
                "needs_human",
                escalation_reason="external processing is not approved for this question or its sources",
                via="qwen: processing approval",
            )
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key:
            return Answer(
                "The model API key is not configured. Please contact the team.", "error", via="qwen"
            )
        chunks, finish, usage = [], None, None
        length, reasoning_length, started = 0, 0, time.monotonic()
        try:
            # No redirects, automatic provider fallback, tools or media uploads.
            # Include system-trusted roots (including Windows) while verifying TLS and hostname.
            with self._response(request, key, state) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if time.monotonic() - started > REQUEST_DEADLINE:
                        raise ValueError("Streaming deadline exceeded")
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    item = json.loads(data)
                    if item.get("error"):
                        raise ValueError("Provider returned an error event")
                    if item.get("usage"):
                        usage = item["usage"]
                        state["usage"] = usage
                    for choice in item.get("choices", []):
                        if choice.get("index", 0) != 0:
                            continue
                        delta = choice.get("delta", {})
                        if delta.get("tool_calls") or delta.get("audio"):
                            raise ValueError("Unexpected non-text model output")
                        reasoning = delta.get("reasoning_content")
                        if reasoning is not None:
                            if not isinstance(reasoning, str):
                                raise ValueError("Invalid reasoning delta")
                            if reasoning and not self.enable_thinking:
                                raise ValueError("Unexpected reasoning while thinking is disabled")
                            reasoning_length += len(reasoning.encode("utf-8"))
                            if reasoning_length > MAX_REASONING_BYTES:
                                raise ValueError("Model reasoning exceeded the response size bound")
                        # Only final content is parsed, logged or published. Reasoning is discarded.
                        piece = delta.get("content") or ""
                        if not isinstance(piece, str):
                            raise ValueError("Invalid text delta")
                        chunks.append(piece)
                        length += len(piece.encode("utf-8"))
                        if length > 4096:
                            raise ValueError("Model reply exceeded the response size bound")
                        finish = choice.get("finish_reason") or finish
            if finish != "stop":
                raise ValueError("Incomplete model reply")
            selection = parse_selection("".join(chunks))
            if isinstance(usage, dict):
                counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
                if all(type(count) is int and count >= 0 for count in counts):
                    log.info("Qwen usage: input_tokens=%d output_tokens=%d", *counts)
            return grounded_answer(selection, entries)
        except ProviderCapacity as error:
            return Answer(
                BUSY_MESSAGE,
                "limited",
                via="qwen: retry busy" if error.attempted else PROVIDER_BUSY,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
            # The reason is a fixed message (validation rule, HTTP status, parse position): it
            # carries no question or FAQ text. Raw replies are logged only when explicitly enabled
            # for local debugging, never in production.
            reason = f"{type(error).__name__}: {error}"[:200]
            log.warning("Qwen request or reply rejected: %s", reason)
            if os.environ.get("GAB_LOG_MODEL_OUTPUT") == "1" and chunks:
                log.warning("Qwen raw reply (GAB_LOG_MODEL_OUTPUT=1): %s", "".join(chunks)[:4000])
            return Answer(
                ERROR_MESSAGE,
                "error",
                escalation_reason=f"model reply rejected: {reason}",
                via="qwen",
            )
