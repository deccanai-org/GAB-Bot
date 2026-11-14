# Architecture

`bot.py` is an entry point. Importing it does not read secrets, open files, construct
a Discord client, load an embedding model, or connect to a service. `create_bot()`
explicitly constructs an independent application; `setup_hook()` initializes FAQ
models and persistent views, synchronizes commands, and starts background jobs.
SIGTERM stops admission, drains bounded work, cancels background jobs, and flushes
snapshots. Final-snapshot failure still closes SQLite and releases process ownership.
The OS-backed owner lock prevents two local processes using the same output directory.

## Boundaries

| Module | Responsibility |
| --- | --- |
| `contracts.py` | Shared `Answer`, role/outcome types, and engine protocol; no provider SDK |
| `conversation.py` | History normalization and tool-free request policy |
| `knowledge.py`, `search.py` | Approved knowledge loading, audience restrictions, retrieval |
| `grounding.py` | Shared source-selection instructions and deterministic source rendering |
| `tutorials.py` | Approved playground links mapped to FAQ IDs, shared by both answer engines |
| `model_limits.py` | Durable per-user question quotas and adapter-bound user identity |
| `model_context.py`, `qwen.py` | Bounded approved context and Qwen3-Omni-Flash selection at the authorized Singapore endpoint |
| `guard.py`, `routing.py`, `redact.py` | Input/output guards, configured contacts, text privacy |
| `discord_common.py` | Mention allowlists, channel keys, readable sources, guild-local destinations |
| `discord_answers.py`, `followup.py` | FAQ replies, explicit delivery results, cards and reminders |
| `support.py`, `slack_app.py` | Support commands and Slack transport |
| `storage.py`, `replies.py` | Sanitized atomic snapshots, structured logs, and JSONL question/request logs |
| `tickets.py` | Durable ticket state, fair polling, and forward scan cursors |
| `operations.py`, `runtime_config.py` | Bounded inference, single ownership, health, metrics, and limits |
| `backups.py` | Consistent SQLite backups, checksums, integrity checks, and safe restore |
| `discord_bot/settings.py` | Collection/export/admin configuration |
| `discord_bot/queries.py` | Query detection, categorization, migration, transactional storage |
| `discord_bot/exports.py` | Permission-scoped history retrieval, sanitized CSV, private delivery |
| `discord_bot/moderation.py` | Per-application moderation policy and state |
| `discord_bot/views.py` | Query explorer and persistent panel UI |
| `discord_bot/app.py` | Composition, Discord events, background jobs, shutdown |

Domain and search code depend on the shared contracts, not the Claude SDK or
Discord. Support imports shared Discord helpers rather than the FAQ adapter.
Services receive configuration explicitly; per-bot state is not stored in module
globals. Provider SDK initialization is deferred until its engine is selected.

## Privacy and delivery

The requester’s source-channel permissions are checked when history is read.
Channel selectors also hide unreadable channel names. Explorer navigation, result
previews, slash exports, and CSV downloads are ephemeral; source filtering alone
does not protect a result posted into a wider destination channel.

Secrets are scrubbed before collection and again at persistence and export
boundaries. CSV cells that could be interpreted as formulas are escaped. Logging
handlers scrub formatted messages and exception text. Redaction is pattern-based;
it cannot recognize every possible credential format or redact screenshot pixels.

Every chunk of a long FAQ reply references the original question, preserving
escalation after restarts. An explicit handoff returns delivery success; only a
successful staff-card send disables the button and confirms delivery. A failed
send leaves the button usable. In-process concurrent clicks share a lock and
produce one card. Successful delivery is independent of local logging success.
Reminded cards continue detecting human replies without sending repeat reminders.

Follow-up state and history/reply cursors live in `faq_state.sqlite3`. Migration
reads staff history in bounded batches and resumes after the saved cursor; tickets
do not expire from tracking because of message volume or age. Pending tickets are
polled fairly by last-check time. Successfully delivered reminder batches are
recorded before card edits, so an edit failure does not repeat a delivered reminder.
A crash between an external Discord send and its local commit remains an
at-least-once delivery window; incremental history reconciliation reduces duplicates
but cannot make Discord and SQLite a single atomic transaction.

## Answer trust

The configured Qwen engine sends sanitized questions, at most four short history
messages and selected approved FAQ entries to Alibaba's Singapore API with the
user's explicit authorization. The endpoint and model are fixed in the adapter.
No raw PDFs, MP4s, attachments, tools or audio are sent. API credentials are used
only in the authorization header. The application publishes only approved text
for IDs present in the actual request, plus the stored video links; model prose
is discarded. Invalid or incomplete selections escalate without another call.

The request is capped at 8,000 serialized UTF-8 bytes, model output at 256 tokens,
and thinking is disabled. Per-user reservations happen before provider access.
The optional search engine remains entirely local, with local-file loading and
ONNX telemetry disabled. There is no automatic external-provider fallback.

Keyword-only fallback always marks a retrieved answer uncertain and escalates it.
It does not reuse semantic-search confidence thresholds as evidence of certainty.

## Persistence and deployment

`output/queries.sqlite3` is the collection source of truth, using transactions,
unique message IDs, and WAL mode. Existing `messages.json` records are imported
and scrubbed once. JSON and CSV snapshots use atomic replacement, refresh every
30 seconds when changed, and flush at shutdown. A failed snapshot does not discard
committed queries. Question and request logs remain append-only JSONL.

The deployment has one replica, a `Recreate` rollout, and an output PVC so pod
replacement preserves SQLite and logs. Apply `output-pvc.yaml` before deploying;
the cluster needs an appropriate default StorageClass or an explicit
`storageClassName`. Existing data in an old `emptyDir` must be copied out before
replacing that pod. The manifest change itself does not migrate live pod data.

SQLite is intended for one active bot process and a filesystem supporting its
locking semantics. Slack should use a separate output/log volume if deployed as
a separate process. Multi-replica consumers need a shared database and event
deduplication design.

## Validation

Run `python -m pytest -q`, `python -m ruff check .`, and
`python -m ruff format --check .`. The regression suite exercises private export
delivery, denied source permissions, secret handling, migration and atomic-write
failure, side-effect-free imports, isolated app instances, moderation, multipart
answers, failed/retried/concurrent handoffs, reminders, and fabricated AI prose
with valid citations.

`scripts/run_eval.py --engine search` grades retrieval against
`tests/eval/questions.yaml`. Embedding-dependent tests skip when the model is not
cached. Passing unit tests with provider fakes does not validate live Discord,
Slack, provider models, credentials, or cluster configuration.


## Production acceptance and operating limits

`python scripts/verify_release.py --full` requires real cached embeddings, zero
skipped tests, p95 search latency under the configured load-test budget, a retrieval
pass rate of at least 90%, and no critical evaluation failures. AI/provider calls
are not used by this gate. CI additionally audits packages, builds the image from
hashed dependency locks, and runs the image offline with a read-only root filesystem.
The base image and CI actions use verified immutable digests/commits.

Inference has a fixed native thread pool, bounded admission, per-user limits, and
conversation ordering. A caller timing out does not free a still-running native
worker. Jobs that expire before starting are canceled. Claude API calls also
have finite timeouts. Exports have concurrency, deadline, scan, row, and byte caps;
large requests fail explicitly rather than silently returning incomplete exports.
Support attachments are size-checked, plaintext attachments are scrubbed, and
concurrent requests cannot bypass cooldowns.

FAQ vectors are precomputed during image creation and validated against model and
knowledge checksums on startup. This avoids recomputing all entries during every
restart. Corrupt or stale caches are regenerated; runtime FAQ edits can still be
served in memory when the cache directory is read-only.

`/health/live` reports event-loop availability. `/health/ready` additionally checks
the gateway, required FAQ initialization, command synchronization, writable state,
validated production channels/permissions, and draining state. A gateway outage
makes the pod unready without making the event loop unhealthy. `/metrics` contains
aggregate counts and timings without user IDs, question text, or API keys.

Production refuses keyword-only startup and validates a single guild, destination
existence, bot permissions, and a staff destination hidden from the default role.
Operators must still review which additional roles can read that staff channel.
Secrets are omitted from settings representations; stdout logs are structured JSON
in production. Optional BOT_LOG_FILE must point into writable storage.

See [operations.md](operations.md) for release, pilot, backup, rollback, and incident procedures.
