# GAB FAQ and Discord query bot

The bot collects query-shaped messages, categorizes and exports them, moderates
configured content, answers from approved project FAQs, and routes support
requests to the team. Discord runs with `python bot.py`; Slack runs with
`gigi slack` (or `python -m gab_faq slack`).

## Local setup

Use Python 3.11+ and a separate test bot/server. Do not run a laptop copy with
the production Discord token while the deployed bot is active.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and set the test credentials. In Kubernetes, secrets
are read from environment variables or files in `/app/secrets/`. Values already
present in the environment take precedence.

```sh
python -m pip install -e . --no-deps   # installs the `gigi` command (editable, reads this checkout)
gigi check                             # config, FAQ files, Qwen readiness; no API calls
gigi ping                              # one live Qwen request: key, endpoint, TLS, reply validation
gigi ask "How do I reset before Product B?" --role annotator [--json] [--fresh-quota]
gigi chat --role qc                    # interactive; earlier turns are thread context
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python bot.py
```

`gigi` is the same as `python -m gab_faq`. Questions take exactly the Discord path (guard,
per-user quota, retrieval, Qwen, code-owned routing); the CLI's quota user is `cli:<you>`, and
`--fresh-quota` uses a throwaway quota store for testing. Secrets pasted with surrounding angle
brackets (`<sk-...>`) are unwrapped with a warning; store them without the brackets.
`scripts/live_probe.py` runs a JSON list of synthetic test questions through live Qwen and
records replies, routing, requests and tokens.

The Discord application needs Message Content Intent and the permissions used by
its enabled features: View Channels, Read Message History, Send Messages, Embed
Links, Attach Files, and Manage Messages for deletion. The persistent explorer
panel is created in `faq_channel_name`.

## Configuration

`config.yaml` retains the existing categories, query phrases, moderation rules,
and GAB channel settings. `channel_names` accepts channel or category names;
threads inherit their parent's live-collection scope. The CSV `section` column
identifies the Discord category. Update phase-specific category names whenever
the project moves to a new phase. Optional top-level `output_dir` defaults to
`output`.

FAQ answering uses `gab_faq.discord.only_in`, `answer_channels`, and the role
channel lists. Each list takes any number of channel names, category names,
`Category/channel` pairs, IDs, or `*` patterns (`Project GAB*/project-related-queries`
covers that channel in every GAB section, including later phases). It answers
new messages in configured answer channels and scoped mentions elsewhere. Direct-message answering is controlled separately. Thread
follow-ups stop when another person takes over. QM documents are available only
in configured QM channels.

## Answer engines

Qwen3-Omni-Flash is the bot's default LLM, including when the engine setting is
omitted. The configuration explicitly selects `engine: qwen` and
`model: qwen3-omni-flash` through Alibaba Cloud Model Studio's Singapore API.
Set `DASHSCOPE_API_KEY` in ignored `.env` or deployment secrets. Do not put the
key in Git, questions, logs or chat messages.

**Qwen is on for questions** (`external_questions_approved: true`, approved by the
project owner on 15 November 2026); earlier thread messages are not sent
(`external_history_approved: false`). Setting `external_questions_approved: false`
turns Qwen off: the bot then answers clear FAQ matches, clarifications, greetings
and unrelated questions locally and hands other GAB questions to a person. The exact
fields sent are listed in [docs/outbound-payload.md](docs/outbound-payload.md).

Qwen can explain and combine retrieved FAQ entries (every cited entry
needs an exact quote; required exceptions are appended verbatim), give general
guidance labelled as not an official GAB requirement, ask a clarification, or hand
the question to a person. Links, staff and routing are always added by code. See
[docs/answer-flow.md](docs/answer-flow.md) for every answer type and its checks.
`gab_faq.local_backstop` is retained only for configuration compatibility and has
no effect on the Qwen engine.

Alibaba limits the whole account to 60 requests a minute. The bot keeps its own cap
(`model_limits.provider_requests_per_minute`, 50); a question past it gets a "busy,
ask again in a minute" reply with no staff card and no use of the user's daily
allowance. See "Provider capacity" in [docs/operations.md](docs/operations.md).

`python scripts/run_live_eval.py --yes` measures real answer quality against
`tests/eval/paraphrases.yaml`. It sends FAQ text to Alibaba and costs money, so it
is never part of the routine `run_eval.py` check.

Set `engine: search` explicitly for local CPU embedding and keyword retrieval
without a model API key or external inference. The `search.model` setting names
that optional embedding model; `gab_faq.model` names the Qwen LLM. A missing Qwen
key disables answering and never switches engines automatically.

Low-confidence or unmatched questions are escalated to the team. Keyword-only
degraded mode always marks results uncertain. Retrieval can select an irrelevant
entry; confidence checks and human handoff remain necessary.
Payment and action requests are routed by code. Contacts come from
`gab_faq.support.contacts`, independently of AI selection.

Docker preloads public embedding weights for the optional local search engine.
Runtime weights are loaded locally, with ONNX telemetry disabled. Qwen context
selection uses local keywords before the bounded request is sent to Alibaba.

Per-user FAQ limits in `gab_faq.model_limits` default to 20 questions per rolling
24 hours and 3 per minute across channels. The local SQLite quota survives
restarts and is included in backups. Failed attempts count toward the cap;
greetings and requests routed directly to staff do not. Questions are limited to
1,500 characters, history to four messages of 400 characters each, and predefined
answers to 6,000 characters. Longer answers escalate instead of being cut off.
Qwen requests have an 8,000-byte serialized UTF-8 cap, including question, history,
FAQ excerpts and request options. This is a byte limit, not a tokenizer count.
Model output is capped at 256 tokens, thinking is disabled, and only text mode is
requested. The longer predefined FAQ reply is rendered locally. Provider errors
consume an attempt so retries cannot bypass the per-user cap.

## Exports and privacy

The panel supports category browsing, recent questions, query CSVs, and chat-log
CSVs. `/export days:7` works in the FAQ channel. All navigation, result previews,
and downloads are **private ephemeral responses**. Source-channel permissions
are checked for the requester; channel selectors hide unreadable channels.
History exports currently read selected text channels, while live capture also
handles thread messages. Archived-thread export is not implemented.

Secrets are scrubbed before query collection, persistence, logs, staff-card
content, and CSV output. CSV formula cells are escaped. Pattern-based redaction
does not cover every credential format or secrets visible inside screenshots.

## Support and follow-up

`/throttle-request` accepts a reason, requested limit, and stage. `/task-issue`
accepts a task ID, description, optional error text, and up to three attachments.
Commands are scoped to the project and rate-limited per person. Staff cards go
to `support.requests_channel`, falling back to `discord.unanswered_channel`.

Public replies never name a staff member: the contact line says "contact
`support.public_contact`" (default "the admin of this project"), and payment
questions are pointed to `support.payment_email` first. Staff names stay on the
private staff cards and in direct messages to the staff. Every reply ends with a
line on what to do next (carry on with the answer, or ask again in more detail) and
a reminder to keep checking the section's #announcements channel.

`repeat_limit` stops one person asking the same question again and again: the ask
that reaches `max_asks` inside `window_minutes` is flagged once to the team instead
of answered, and later repeats get a short "already flagged" reply.

There are two staff channels. Unanswered FAQ questions get a staff card in
`discord.unanswered_channel` (`faq-bot-unanswered`) at once, with a persistent
"Mark as answered" button. Questions still open after `followup.after_minutes`
are listed in `followup.reminder_channel` (`faq-bot-followups`; if it doesn't
exist, the reminder goes to `faq-bot-unanswered`). Make both channels private.
Each open card gets one reminder. Reminded cards keep
checking for replies. The durable ticket index and persisted scan cursors keep old questions tracked
across restarts and large histories.

The asker can escalate a confident answer using ?Didn't help? Ask a person?.
Every part of a long reply references the original question. The button changes
to ?Sent to the team? only after the staff card is delivered. Failed delivery
keeps it usable and reports the failure instead of confirming success.

## Data and deployment

| File | Purpose |
| --- | --- |
| `output/queries.sqlite3` | Transactional collected queries; source of truth |
| `output/messages.json`, `output/messages.csv` | Atomic snapshots, refreshed every 30 seconds and at shutdown |
| `output/faq_questions.jsonl`, `output/faq_unanswered.jsonl` | Sanitized FAQ audit logs |
| `output/support_requests.jsonl` | Sanitized support request metadata |
| `output/faq_panel_id.json` | Persistent explorer panel IDs |
| Optional `BOT_LOG_FILE` | Redacted application logs; production also emits JSON to stdout |
| `output/faq_state.sqlite3` | Durable tickets and scan cursors |
| `output/model_usage.sqlite3` | Persistent per-user FAQ quotas; user IDs and timestamps only |

Existing JSON query data is migrated and scrubbed on first startup. Query inserts
are committed individually; a failed snapshot does not discard committed rows.

The Kubernetes deployment uses a single replica, a Recreate rollout, and the
output PVC in `k8s-manifests/prod/output-pvc.yaml`. Provision that PVC before
deploying. Its StorageClass must match the cluster. Copy any required data from
the old pod's `emptyDir` before replacing it; applying manifests does not migrate
that live data. Slack should use its own output/log volume.

## Updating knowledge and evaluating

Edit numbered entries in `knowledge/current/`; keep IDs unique. Front matter
contains title, audience, phase, and update date. Archived or unapproved documents
and documents containing recognized secrets are excluded. Old phases belong in
`knowledge/archive/`.

**New phase checklist.** Move the previous phase's files to `knowledge/archive/`
(add `status: archived` to their header), add the new phase's files to
`knowledge/current/`, list each new file in `knowledge/current/entry-policy.yaml`
(`external_processing_approved: true`, or Qwen will hand its questions to staff),
point `playground-videos.yaml` at the new entry IDs, and replace
`tests/eval/questions.yaml` with questions for the new phase. Discord sections whose
name starts with "GAB Phase" are picked up automatically (answering and question
collection). Engine tests run against the frozen Phase 6 FAQ in
`tests/fixtures/knowledge-phase6/`, so they don't change with the phase.

Playground video references live in `knowledge/current/playground-videos.yaml`.
Each video maps to explicit FAQ IDs. Local search returns the approved written
solution followed by its relevant video links. Use supplied HTTPS URLs; a missing
URL displays the recording title and asks the user to get the link from their QM.
Edits to the catalog reload on the next question. PDF knowledge remains numbered
text FAQ entries. See [source import status](docs/source-import-status.md) for
coverage, source precedence, and the mapping of supplied links to archive videos.

```sh
python scripts/run_eval.py --engine search
```

The Phase 7 evaluation (`tests/eval/questions.yaml`) contains 23 questions and fails below the configured
pass threshold or on a critical failure. Embedding-dependent unit tests skip
when the local model is not cached. Qwen HTTP/protocol tests use mocked responses;
they do not establish live key access or provider answer quality.
Current acceptance evidence is recorded under artifacts/; rerun it for each release.

See [docs/architecture.md](docs/architecture.md) for service boundaries,
persistence, delivery guarantees, and remaining limits.


## Production gates

The supported deployment target is one Discord server and one active bot process.
Run `python scripts/verify_release.py --full` with Python 3.11. It caches the real
model/index, prohibits skipped tests, checks retrieval quality and latency, and
runs static checks. CI also audits dependencies and tests the non-root image with
a read-only filesystem and no network. Production dependencies are hashed in
`requirements.lock`; Linux dev/CI dependencies are in `requirements-dev.lock`.
Regenerate them with `python scripts/lock_requirements.py` under Python 3.11.

The deployment template deliberately uses `release-required`. Render an actual
release only after building, testing, and publishing the image, using its registry
digest with `scripts/render_release.py`. No registry push or cluster update is
performed by validation scripts. See [docs/operations.md](docs/operations.md).
