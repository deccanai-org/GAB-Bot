# Qwen3-Omni-Flash integration

Engine `qwen`, model `qwen3-omni-flash`, Alibaba Cloud Model Studio, Singapore endpoint
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`. Credentials come only from
`DASHSCOPE_API_KEY` (ignored `.env`, environment, or the `/app/secrets` file mount). TLS uses the
system trust store with certificate and hostname verification; redirects are never followed.

## Live results (15 November 2026, evening)

Qwen was turned on by the project owner (`external_questions_approved: true`; history still not
sent). `scripts/run_live_eval.py` against `tests/eval/paraphrases.yaml` (226 assistant-written,
informal questions: 191 answerable, 35 off-topic/personal/injection), real Qwen, real FAQ:

| Run | Answerable correct | Off-topic handled without publishing FAQ/general text |
| --- | --- | --- |
| First live run, before fixes | 115 / 191 (60%) | 20 / 35 |
| After the fixes below | **178 / 191 (93%)** | 30 / 35 |

Median reply 1.7 s, 95th percentile 2.4 s; about 1,300 input and 150-250 output tokens a request.
Reports: `artifacts/live-eval-2026-11-15.json` (before), `artifacts/live-eval-2026-11-15-r2.json`.

What the first live run exposed, and the fix:
- 63 of 76 failures were good answers rejected by validation: Qwen omitted `"sources"` on
  non-answers, wrote `{"answered": true}`, joined verbatim quote fragments with "...", quoted entry
  titles, and restated "Phase 6.1"/"Stage 4". The envelope and quote rules now accept these shapes
  (see [answer-flow.md](answer-flow.md)); answer text is still checked for numbers and policy.
- A rejected explanation now shows the selected entries' approved text instead of a staff card.
- Retrieval misses on paraphrases ("which memory setting", "wipe old chats", "link chatgpt to my
  drive"): a title-vocabulary retry and a few curated synonyms.
- Two live-task false positives ("which turn should I mark as the key turn") were narrowed.
- Found after the second run and fixed: general guidance that stated GAB policy ("no set daily
  hour requirement... meet deadlines") is now withheld and the question goes to a person.

Not solved: about 7 in 100 answerable questions still get a related but not the best entry or a
hand-off; 3 off-topic questions got (harmless) labelled general guidance. The question sets were
written by the assistant, not taken from real freelancers: re-run on real pilot questions.

## Configuration status

- Questions are sent to Qwen; earlier thread messages are not (`external_history_approved:
  false`). Setting `external_questions_approved: false` turns Qwen off: the bot then answers clear
  FAQ matches, clarifications, greetings and unrelated questions locally and hands every other GAB
  question to a person. The exact fields sent are in [outbound-payload.md](outbound-payload.md).
- The answer modes (grounded explanations, labelled general guidance, clarifications, code-owned
  routing) are described in [answer-flow.md](answer-flow.md).
- The unit tests (455) use mocked HTTP responses and synthetic fixtures; they check validation,
  rendering, routing and limits. Live quality is the table above, not the unit tests.

## Provider facts this design relies on

The [model page](https://www.alibabacloud.com/help/en/model-studio/qwen3-omni-flash) states that
structured output is unsupported and the
[access guide](https://www.alibabacloud.com/help/en/model-studio/qwen-omni) requires streaming and
supports disabling thinking. The adapter therefore streams text only, with thinking off, asks for a
JSON object, and validates it locally (`grounding.grounded_answer`).

## Limits

| Limit | Default | Setting |
| --- | --- | --- |
| Estimated input tokens per request | 2,000 (bytes / 3) | `model_limits.max_input_tokens` |
| Serialized request size | 8,000 bytes | `model_limits.max_prompt_bytes` |
| Output tokens | 300 | `model_limits.max_output_tokens` |
| Provider requests per question (all retries) | 3 | `model_limits.provider_calls_per_question` |
| Rate-limit retries per request (429/502/503/504) | 2 | `model_limits.provider_max_retries` |
| Provider requests per minute, whole bot | 50 | `model_limits.provider_requests_per_minute` |
| Provider tokens per minute, whole bot | 90,000 | `model_limits.provider_tokens_per_minute` |
| Questions per user | 20 / rolling 24 h, 3 / minute | `questions_per_day`, `questions_per_minute` |

The rules and the best-matching entry with its required exceptions are never cut to fit; older
history is dropped first, and if the essential part still does not fit, no request is sent and the
asker is told to ask about one part. Measured locally on 8 representative questions, 2 to 8 complete
entries fit (about 0.9k to 2.0k estimated tokens).

## Historical measurements (do not describe the current engine)

On 15 November 2026 an earlier version of this integration (Qwen selected FAQ IDs only and the
bot published the stored text; lenient ID parsing; embedding backstop on; questions sent to
Alibaba) was scored live against assistant-written paraphrase sets. Those figures were measured
before the current answer contract, the external-processing gate and the retrieval rewrite, and
must not be quoted for the current bot. Re-run `scripts/run_live_eval.py` on real pilot questions
after external processing is approved.
