# Outbound payload to Qwen (Alibaba Model Studio, Singapore)

Status (15 November 2026): **questions are sent; thread history is not.** The project owner
turned Qwen on, so `external_questions_approved` is `true` in `config.yaml`;
`external_history_approved` stays `false` (earlier messages are used only for local retrieval).
This page lists exactly what is sent, field by field.

Approving "general answers" does not by itself approve sending other data: each flag below is set
deliberately by the data owner.

| Flag | Current | Effect when `true` |
| --- | --- | --- |
| `external_questions_approved` | `true` | Sanitized freelancer questions and approved FAQ excerpts are sent. |
| `external_history_approved` | `false` | Up to 4 earlier messages from the same conversation would also be sent. |

Each FAQ document also needs `external_processing_approved: true` (in its front matter or in
`knowledge/current/entry-policy.yaml`). An entry without it is never sent; the question goes to a
person instead.

## Destination

`POST https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`, TLS verified, no
redirects followed.

HTTP headers: `Authorization: Bearer <DASHSCOPE_API_KEY>` and `Content-Type: application/json`.
The key is never placed in the body.

## Body: the complete list of fields

The body is built only by `Qwen.build_request` (`gab_faq/qwen.py`); `tests/test_answer_modes.py`
fails if a field is added or removed without updating this page.

| Field | Value |
| --- | --- |
| `model` | `qwen3-omni-flash` |
| `messages` | See below. |
| `max_tokens` | `model_limits.max_output_tokens` (300) |
| `temperature` | `0` |
| `enable_thinking` | `false` |
| `modalities` | `["text"]` |
| `stream` | `true` |
| `stream_options` | `{"include_usage": true}` (token counts for cost accounting) |

No `tools`, `tool_choice`, `functions`, `response_format`, files, audio or images are ever sent
(`conversation.assert_no_tools` refuses such a request).

### `messages`

1. **system**: the fixed answering rules (`grounding.SOURCE_SELECTION_RULES`) followed by
   `<faq>...</faq>` containing the selected FAQ entries. For each entry: its ID, title, intended
   audience, version, status, required-entry IDs and body text. URLs in the body are replaced by
   `[stored link]`; links are attached to replies by code after the model answers. When no entry
   matched, a fixed note replaces the entries.
2. **history** (only if `external_history_approved: true`): up to 4 earlier messages by the asker
   and the bot in the same thread or reply chain, each at most 400 characters, secrets scrubbed.
   Messages that try to override instructions are left out.
3. **user**: `<asker_role>annotator|qc|qm|unknown</asker_role>` and
   `<question>...</question>`, the question with recognized secrets and Discord mentions removed,
   at most 1,500 characters.

### Never sent

- Discord or Slack user IDs, usernames, display names, roles beyond the four role labels above,
  channel names or IDs, message links, server names.
- Staff names, staff Discord IDs or any mention text.
- Attachments, screenshots, PDFs, videos, or any URL.
- Queue-manager (QM) documents or sections, unless the asker is in a configured QM channel.
- FAQ entries without `external_processing_approved: true`, archived or superseded entries.
- Other users' messages.

## Size and rate bounds

- Whole request: at most `max_prompt_bytes` (8,000) serialized UTF-8 bytes and about
  `max_input_tokens` (2,000) estimated tokens (bytes / 3, a deliberate over-estimate; actual usage
  is logged from the provider's counts). The rules and the best entry with its required exceptions
  are kept whole; older history is dropped first; if the essential part still does not fit, no
  request is sent and the asker is told to ask about one part.
- Provider-wide: `provider_requests_per_minute` (50) and `provider_tokens_per_minute` (90,000),
  shared by every worker through `output/provider_usage.sqlite3`.
- Per question: at most `provider_calls_per_question` (3) requests, including the one targeted
  retrieval retry and any 429/5xx retries.
- Per user: `questions_per_day` (20, rolling 24 h) and `questions_per_minute` (3), enforced before
  any request.
