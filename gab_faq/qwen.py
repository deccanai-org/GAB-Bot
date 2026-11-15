"""Qwen3-Omni-Flash selection through the user-approved Alibaba Singapore API."""

from __future__ import annotations

import json
import logging
import os
import time

import httpx

from .config import QWEN_MODEL
from .contracts import Answer
from .conversation import assert_no_tools
from .grounding import SOURCE_SELECTION_RULES, render_sources
from .model_context import (
    PromptTooLong,
    bounded_history,
    entry_context,
    pack_entries,
    request_bytes,
)
from .model_limits import ModelLimits
from .redact import clean_untrusted
from .search import NOT_FOUND

log = logging.getLogger(__name__)
ENDPOINT = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = QWEN_MODEL
ERROR_MESSAGE = "I couldn't complete the FAQ lookup. A team member can help with this question."


class Qwen:
    def __init__(self, knowledge, *, model=MODEL, limits=None, max_history_messages=4, client=None):
        if model != MODEL:
            raise ValueError(f"Qwen requires model {MODEL!r}")
        self.knowledge = knowledge
        self.model = model
        self.limits = limits or ModelLimits()
        self.max_history_messages = min(max_history_messages, 4)
        # The module-level stream context opens and closes its client per call.
        self.client = client or httpx

    def build_request(self, question, role="unknown", history=None):
        question = clean_untrusted(question).strip()
        history = bounded_history(history, self.max_history_messages, self.limits)

        def make_request(entries):
            system = (
                SOURCE_SELECTION_RULES
                + '\nReturn only JSON, e.g. {"outcome":"answered","sources":["A1"]}. No Markdown fences.\n<faq>\n'
                + entry_context(entries)
                + "\n</faq>"
            )
            return assert_no_tools(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        *history,
                        {
                            "role": "user",
                            "content": f"<asker_role>{role}</asker_role>\n<question>{question}</question>",
                        },
                    ],
                    "max_tokens": self.limits.max_output_tokens,
                    "enable_thinking": False,
                    "modalities": ["text"],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            )

        return pack_entries(self.knowledge, role, question, history, self.limits, make_request)

    def answer(self, question, role="unknown", history=None):
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key:
            return Answer(
                "The model API key is not configured. Please contact the team.", "error", via="qwen"
            )
        try:
            request, entries = self.build_request(question, role, history)
        except PromptTooLong as error:
            return Answer(str(error), "limited", via="qwen: prompt limit")
        except Exception:
            log.exception("Qwen FAQ context could not be prepared")
            return Answer(ERROR_MESSAGE, "error", via="qwen")
        chunks, finish, usage = [], None, None
        length, started = 0, time.monotonic()
        try:
            # No retries, redirects, automatic provider fallback, tools or media uploads.
            with self.client.stream(
                "POST",
                ENDPOINT,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                content=request_bytes(request),
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if time.monotonic() - started > 25:
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
                    for choice in item.get("choices", []):
                        if choice.get("index", 0) != 0:
                            continue
                        delta = choice.get("delta", {})
                        if (
                            delta.get("tool_calls")
                            or delta.get("reasoning_content")
                            or delta.get("audio")
                        ):
                            raise ValueError("Unexpected non-text model output")
                        piece = delta.get("content") or ""
                        if not isinstance(piece, str):
                            raise ValueError("Invalid text delta")
                        chunks.append(piece)
                        length += len(piece.encode("utf-8"))
                        if length > 4096:
                            raise ValueError("Model selection exceeded the response size bound")
                        finish = choice.get("finish_reason") or finish
            if finish != "stop":
                raise ValueError("Incomplete model selection")
            selection = json.loads("".join(chunks))
            if not isinstance(selection, dict) or set(selection) != {"outcome", "sources"}:
                raise ValueError("Invalid model selection shape")
            outcome, sources = selection["outcome"], selection["sources"]
            if not isinstance(sources, list) or len(sources) > 3:
                raise ValueError("Invalid source count")
            if isinstance(usage, dict):
                counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
                if all(type(count) is int and count >= 0 for count in counts):
                    log.info("Qwen usage: input_tokens=%d output_tokens=%d", *counts)
            if outcome == "not_in_faq" and not sources:
                return Answer(NOT_FOUND, "not_in_faq", via="qwen")
            if outcome == "needs_human" and not sources:
                return Answer(
                    "A team member can help with this question.", "needs_human", via="qwen"
                )
            return render_sources(entries, sources, outcome, via="qwen")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            log.warning("Qwen request or source selection failed; no retry attempted")
            return Answer(ERROR_MESSAGE, "error", via="qwen")
