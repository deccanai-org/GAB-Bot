# Answer flow

How Gigi turns a freelancer's message into a reply. Code: `gab_faq/guard.py` (runs first, for
every engine), `gab_faq/policy.py`, `gab_faq/qwen.py`, `gab_faq/grounding.py`, `gab_faq/routing.py`.

## Order of checks

1. **Guard (code only, no model).** Question length; instruction-override attempts (refused, no
   staff); requests for an action (reset, throttle, payment, role) routed to a person; questions
   about the asker's own pay routed to payment; requests to choose a rating or write a
   justification for a live task (declined, with an offer to explain the rubric); greetings and
   thanks; then the per-user quota (20 per rolling 24 h, 3 per minute).
2. **Local retrieval** (BM25 over every current approved FAQ entry the asker may see; superseded
   entries excluded; documented `requires` exceptions always travel with their entry).
   - A clear FAQ match (the question is an entry's title) is answered locally with the approved
     text and its stored links. No model.
   - A bare ambiguous question ("which video?", "which account?") gets a local clarification.
3. **Qwen unavailable** (`external_questions_approved: false`, or no API key): nothing is sent.
   GAB questions go to a person; unrelated ones get a short redirect without staff. Qwen has been
   ON since 15 November 2026 (questions only; thread history is not sent).
4. **Qwen** receives the rules, the best complete entries within the token budget and the
   question, and must reply with one JSON object (validated in `grounding.py`).
5. **One targeted retrieval retry** when Qwen asks for more evidence, the first search found
   nothing, or Qwen called a question with a GAB keyword "unrelated". The retry searches with the
   question's subject words that appear in FAQ titles (generic words such as "good" or "use"
   dropped). If that leaves no words, nothing is sent and the question is redirected.
6. Still no entry, but the question is GAB-related: Qwen may give **general guidance only**; with
   no entries it cannot state GAB policy. Otherwise the question goes to a person (GAB) or is
   redirected (unrelated).

## Answer types

| Type | Outcome | Model? | Staff? | What the asker sees |
| --- | --- | --- | --- | --- |
| Clear FAQ match | `answered` | No | No | Approved entry text, stored video links, `(FAQ: ID)` |
| Interpretation | `answered` | Yes | No | Qwen's explanation, then required exceptions verbatim, stored links, `(FAQ: IDs)` |
| General explanation | `general` | Yes | No | Labelled "General guidance (not an official GAB requirement)" |
| Company policy | `answered` from entries, else `needs_human` | Yes | Only if missing | Never filled from general knowledge |
| Ambiguous | `clarification` | Local or Yes | No | One focused question |
| Unrelated | `unrelated` | Only if GAB words | No | "I help with GAB project questions..." |
| Greeting / thanks | `small_talk` | No | No | A short natural reply |
| Human action / unresolved | `needs_human` | Usually no | Yes | What the bot can't do + who handles it |
| Live task help / injection | `declined` | No | No | What the bot can do instead |
| Provider failure | `error` | Attempted | Yes | "A team member can help" |
| Busy / limits | `limited` | No | No | Try again later |

### What model text is accepted

- **Explanations** cite supplied entry IDs (the prompt asks for up to 3; 5 are accepted), each with
  a quote copied from that entry's title or body. Accepted quote shapes: verbatim (case,
  whitespace and punctuation aside); verbatim fragments joined with "..." in the entry's order; or
  a quote whose longest verbatim run is at least 6 words and half the quote. Digits, spelled-out
  quantities ("three days") and decimals must appear in the cited entries (section heading, title,
  body or phase version; "4" is supported by "4.1"). Pay, account-status and expiry claims must be
  quoted verbatim. Entries an answer `requires` are appended verbatim, so an explanation cannot drop
  an exception.
- **General guidance** (max 900 characters) may not contain numbers that the supplied entries do
  not, deadlines, pay, account status, claims about what GAB/the guidelines require, or GAB process
  terms (Product A/B, seed prompt, debug JSON, Reset ID, key turn, Stage 4...): those are answered
  from entries, never labelled "not official". It is always labelled.
- **All model text**: no URLs, mentions, staff names or contact details; no claim that a reset,
  payment, ticket or message happened; no rating choice or ready-to-submit justification.
- **When the wording fails a check but the selected entries are valid**, the reply is those
  approved entries verbatim with their stored links (`via: qwen: approved text (explanation
  rejected)`), not a staff hand-off. Only a reply with no valid entry (or an invalid envelope)
  becomes an error. Nothing the model writes is published unchecked.
- Replies seen live that are normalised before validation: `{"answered": true}` for
  `{"outcome": "answered"}`, and a missing `sources` list on non-answers (an explanation must still
  name its sources).

## Human escalation

Contacts are stored in `config.yaml` as quoted ID strings; mentions are built in code:

| Category | Mention |
| --- | --- |
| `task_qc` | `<@1533459501393379488> <@1568512803986346028>` |
| `payment` | `<@1533459501393379488>` |
| `playground` | `<@1152255102778884159>` |
| `environment_reset` | `<@1490962186690887823>` |

- Escalation happens only when a person must act or the information is not available; asking
  *how* to reset is answered from the FAQ, asking the bot *to* reset is routed.
- `routing.resolve_route`: the keyword classifier decides, with payment, playground and
  environment_reset taking precedence over the `task_qc` catch-all. A model's `category` is used
  only when the classifier found nothing specific, and only if it is one of `task_qc`, `payment`,
  `playground`, `environment_reset`, `throttle`; anything else is ignored.
- A throttle increase is a distinct request: routed to `task_qc` with a pointer to
  `/throttle-request`.
- "Everything else" means unresolved GAB support issues; unrelated questions never reach staff.
- The staff card pings nobody; each routed person gets one DM per card (duplicate IDs collapse;
  repeat clicks on "Ask a person" find the existing card).
- The bot never says an action succeeded; it only says who will handle it.

## Links

URLs live with their entries (`playground-videos.yaml` for the 13 tutorial videos, inline links in
FAQ text). The model sees `[stored link]` instead of URLs and cannot add links; code attaches each
cited entry's exact stored URLs. Tests pin all 13 video URLs.

## Prompt injection

Questions, history and FAQ text are data. Override attempts are refused by code before any model
call; history messages containing them are not uploaded; model output is validated whatever the
input said.

## `local_backstop` (explained, unchanged)

`gab_faq.local_backstop` in `config.yaml` is `false` and **currently has no effect**: the value is
parsed into `Settings.local_backstop`, but `engine.py` never passes an embedding search to the Qwen
engine, so `Qwen.search` is always `None` and nothing reads it.

In the earlier engine, `true` meant: when Qwen said "not in the FAQ" or failed, run the local
embedding search and, if it returned a *confident* match, post that FAQ entry instead of escalating.
It needed the embedding model loaded at startup. Re-enabling that would change three things:
fewer staff hand-offs during provider outages, answers chosen by embedding similarity without the
model's interpretation, and the embedding model's memory/startup cost. The setting was left as is;
changing it needs an explicit decision.

## Budgets and rate limits

See [qwen-validation.md](qwen-validation.md) for the limits table and
[outbound-payload.md](outbound-payload.md) for what is sent. All Qwen requests (first pass, retry,
general-only) share the provider-wide RPM/TPM quota, the per-question call budget (3) and the
per-user quota.

## Testing

`tests/test_answer_modes.py`, `tests/test_reliability.py` and `tests/test_cli.py` use mocked HTTP
responses and synthetic fixtures, with network connections blocked. They verify the application's
validation, rendering, routing and limits, not live Qwen answer quality. Live quality is measured
separately with `scripts/run_live_eval.py` (226 paraphrased questions) and `scripts/live_probe.py`
(answer-mode probes); see [qwen-validation.md](qwen-validation.md).
