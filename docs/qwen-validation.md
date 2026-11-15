# Qwen3-Omni-Flash integration

The user explicitly authorized the transfer of sanitized questions, short history
and relevant approved internal FAQ excerpts to Alibaba Cloud Model Studio's
Singapore endpoint. This supersedes the earlier local-only operating instruction.
The active and default engine is `qwen`, with `model: qwen3-omni-flash` explicitly
set in `config.yaml`. Omitting either setting preserves the Qwen default;
an incompatible model name is rejected. Local `search` remains an explicit alternative.

The fixed API endpoint is
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`, with
model `qwen3-omni-flash`. Credentials are read only from `DASHSCOPE_API_KEY` in the
environment/ignored `.env` or the existing deployment secret-file mechanism.
The prior provider key is unused and is not renamed or sent to Alibaba.

The [official model page](https://www.alibabacloud.com/help/en/model-studio/qwen3-omni-flash)
states that structured output is unsupported. The
[official access guide](https://www.alibabacloud.com/help/en/model-studio/qwen-omni)
requires streaming for this model and supports disabling thinking. Accordingly,
the adapter requests streaming text only, with thinking off, prompts for short
selection JSON and validates that JSON locally. No unsupported JSON-mode parameter
is used. Only approved text for selected available IDs is published.

Existing caps remain 20 attempts per user per rolling 24 hours, 3 per minute,
1,500 question characters, four history messages of up to 400 characters, and
6,000 rendered answer characters. Additional provider caps are an 8,000-byte
serialized request and 256 output tokens. The byte cap includes all request
options and is not represented as an exact tokenizer measurement. Only complete
FAQ entries fit into the context; entries are not truncated. Role restrictions
apply to documents and individual sections before any context is sent.

No retries, HTTP redirects, tools, media output or alternative provider calls are
enabled. API failures, invalid source selections, truncated output and unavailable
FAQ answers escalate. Greetings and direct support/payment requests remain local.
Quota reservations are durable and atomic, including provider failures. Logs only
include validated numeric token usage, never provider response bodies or keys.

Qwen unit tests use a mocked HTTP transport to test streaming, destination,
authorization placement, redaction, role filtering, limits, errors and escalation.
The optional local search still has a test that blocks network connections.
Live Alibaba access and answer quality require a correctly scoped key and have
not been claimed by these tests. Reports are in `artifacts/qwen-tests.xml` and
`artifacts/qwen-local-eval.json`.

Observed checks: 282 tests passed with no failures or skips; all 40 offline FAQ
evaluation cases passed. Lint, formatting and configuration checks passed. The
evaluation command defaults to local search even when the application uses Qwen,
so routine evaluation cannot accidentally incur provider charges. The key slot
was prepared without a value, and no live Alibaba request was made.
