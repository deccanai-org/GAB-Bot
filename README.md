# GAB FAQ and Discord query bot

The bot collects query-shaped messages, categorizes and exports them, moderates
configured content, answers from approved project FAQs, and routes support
requests to the team. Discord runs with `python bot.py`; Slack runs with
`python -m gab_faq slack`.

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
python -m gab_faq check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m gab_faq chat
python bot.py
```

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
channel lists. It answers new messages in configured answer channels and scoped
mentions elsewhere. Direct-message answering is controlled separately. Thread
follow-ups stop when another person takes over. QM documents are available only
in configured QM channels.

## Answer engines

- `claude`: Claude selects FAQ IDs from the approved knowledge available to the
  asker. Needs `ANTHROPIC_API_KEY`; without it the bot does not answer.
- `search`: embedding and keyword retrieval on the local CPU; no AI and no API key.

Anthropic is the only AI provider the bot supports.

**AI prose is never published.** The application renders the selected approved
entries and their IDs. A valid citation cannot be used to attach invented model
names, numbers, or claims that the bot performed an action. A model can still
select an irrelevant entry; confidence checks and human handoff remain necessary.
Invalid AI selections, unavailable services, and timeouts are escalated to a team
member instead of answering. Keyword-only degraded mode always marks results uncertain.
Payment and action requests are routed by code. Contacts come from
`gab_faq.support.contacts`, independently of AI selection.

The first embedding run downloads the configured model into `models/`; Docker
preloads it while building. With the `claude` engine, Anthropic receives sanitized
questions, limited history, and the approved FAQ text available to the asker. Its
data-handling terms still apply.

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

Unanswered FAQ questions get staff cards with a persistent resolution button.
After `followup.after_minutes`, open cards get one reminder. Reminded cards keep
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

Existing JSON query data is migrated and scrubbed on first startup. Query inserts
are committed individually; a failed snapshot does not discard committed rows.

The Kubernetes deployment uses a single replica, a Recreate rollout, and the
output PVC in `k8s-manifests/dev/output-pvc.yaml`. Provision that PVC before
deploying. Its StorageClass must match the cluster. Copy any required data from
the old pod's `emptyDir` before replacing it; applying manifests does not migrate
that live data. Slack should use its own output/log volume.

## Updating knowledge and evaluating

Edit numbered entries in `knowledge/current/`; keep IDs unique. Front matter
contains title, audience, phase, and update date. Archived or unapproved documents
and documents containing recognized secrets are excluded. Old phases belong in
`knowledge/archive/`.

```sh
python scripts/run_eval.py --engine search
python scripts/run_eval.py --engine claude
```

The evaluation currently contains 67 questions and fails below the configured
pass threshold or on a critical failure. Embedding-dependent unit tests skip
when the model is not cached. Provider-fake unit tests do not verify live APIs.
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
