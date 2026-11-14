# Production operations

## Supported target and release gates

One Discord server, one active instance, SQLite on a persistent filesystem with
reliable locking. The bot owns its output directory through an OS lock. Horizontal
replicas and a production Slack rollout are outside this release target.

Use Python 3.11. The hashed locks target Linux x86_64; ordinary requirements remain
available for local Windows development. Run:

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
python scripts/verify_release.py --full
python -m pip_audit --strict --progress-spinner off
docker build -t gab-faq:release-candidate .
docker run --rm --read-only --network none \
  --tmpfs /tmp:rw,size=256m \
  --tmpfs /app/output:rw,uid=10001,gid=10001,size=64m \
  --memory 1536m --cpus 1.5 \
  gab-faq:release-candidate python scripts/smoke_image.py
```

Full acceptance prohibits skipped tests, requires a real model, checks the
67-question retrieval evaluation (at least 90%, no critical failures), and runs
100 concurrent-search requests through four workers with a p95 budget of five
seconds. This is a local-search gate, not a promise about external-provider latency.
Known evaluation misses must still be reviewed; uncertain answers are escalated.
Keep a separate set of paraphrases and actual pilot failures for future regression
cases instead of weakening the evaluator to make a release pass.

CI performs these gates with immutable action references and a pinned base image.
Passing local checks does not mean a GitHub workflow or live deployment has run.

For a trusted corporate TLS interception environment, provide its approved public
CA bundle as a BuildKit secret:

```sh
docker build --secret id=build_ca,src=/path/to/approved-ca-bundle.pem -t gab-faq:release-candidate .
```

The bundle is used only while installing dependencies and fetching model files.
It is not copied into the image. Never disable TLS or package hash verification.
If runtime Discord/provider traffic also requires that CA, have the platform owner
mount the approved bundle and configure SSL_CERT_FILE/REQUESTS_CA_BUNDLE explicitly.

## Test-server pilot

Use a separate Discord application, token, and server. Configure channel/category
names, enabled Message Content Intent, staff contacts, and private staff channels.
Keep GAB_ENVIRONMENT=staging during the pilot. Verify:

- startup, slash-command sync, reconnect, and restart without duplicate panels;
- representative FAQ questions for each role, off-topic queries, and QM isolation;
- private exports from a requester with limited channel access;
- long replies, escalation ownership, delivery failure, retry, and cooldowns;
- task/throttle requests, attachment limits, and plaintext credential redaction;
- reminder delivery, replies after a reminder, and recovery of old pending cards;
- SIGTERM during an active request, committed data recovery, and backup restore.

Production readiness additionally validates one guild, resolved answer/staff
channels, required bot permissions, a staff destination hidden from the default
role, synchronized commands, writable query/ticket state, and an initialized FAQ
engine with real embeddings. Review all other roles allowed into staff channels;
checking the default role alone cannot prove every role assignment is private.

## Deploy and roll back

1. Save and verify current state before replacing an existing pod. Old emptyDir
   data must be copied out first; PVC configuration does not migrate it.
2. Provision `k8s-manifests/dev/output-pvc.yaml` with the cluster's StorageClass.
   Confirm the volume is writable by UID/GID 10001 and supports SQLite locking.
3. Create/update the existing Kubernetes secret through the organization's secret
   manager. Keep tokens out of source, image build arguments, and shell history.
4. Publish the tested image to the existing registry and obtain its registry digest.
5. Render the actual manifest, replacing the intentionally unusable template tag:

```sh
python scripts/render_release.py \
  --image REGISTRY/REPOSITORY@sha256:VERIFIED_DIGEST \
  --output artifacts/deployment.yaml
```

Apply the rendered deployment through the approved delivery pipeline and wait for
readiness. The rollout is Recreate, so expect a brief interruption; two consumers
must not run concurrently with the same token/output directory. Set contact mention
IDs when staff pings are required. The template enables GAB_ENVIRONMENT=production.

For rollback, render/apply the previous verified digest. Preserve the PVC. The
current schema changes are additive; future destructive migrations need their own
backup and compatibility plan. Do not restore a database over an active process.

## Health, alerts, and capacity

- `/health/live`: event loop is serving requests. A gateway outage alone does not
  make this fail.
- `/health/ready`: gateway, initialization, command sync, storage writes, production
  routes, and admission/draining state.
- `/metrics`: aggregate, low-cardinality counters/gauges; no questions, tokens,
  or user labels. Metrics reset on process restart.

The health port is internal; no public Service or ingress is created. Configure
your Prometheus target's job as `gab-faq`, or adapt the sample rules in
`monitoring/alerts.yaml`. Deliver alerts through the existing incident system.
The repository does not provision a monitoring server or notification account.

Initial resource budgets are 250m/512Mi requests and 1500m/1536Mi limits. Confirm
these on the actual node during the pilot. Watch queue saturation, timeouts, gateway
disconnects, disk space, failed staff operations, and unresolved-ticket age. Native
inference has fixed worker limits even when callers time out. A native library
that hangs cannot be force-killed safely inside its Python thread; the pod's
termination grace period is the final process boundary.

For gateway outages, inspect connectivity and permissions before restarting. For
storage errors, stop rollout, inspect free space/mount health, and retain the PVC.
For FAQ quota exhaustion, the bot sends a local limit reply without another
lookup or staff-card flood. Missing embedding weights use uncertain keyword
retrieval, never an external model fallback. Keep quota state on the output PVC
and include it in backup/restore. Do not increase workers before measuring load.

## Backups, restore, and retention

```sh
python scripts/manage_data.py backup --source output --destination /backup/unique-snapshot
python scripts/manage_data.py verify --source /backup/unique-snapshot
# Stop the bot first; destination must be a new empty directory:
python scripts/manage_data.py restore --source /backup/unique-snapshot --destination restored-output
```

Backups use SQLite's online backup API and include query/ticket databases and panel
IDs, with SHA-256 verification and SQLite integrity checks. Each database is
consistent individually; the two databases are not one cross-file transaction.
JSONL audit files are not included by this tool; archive those separately if needed.
Test restoration regularly and store encrypted backups off the bot's PVC with
appropriate access controls. A backup on the same disk does not protect against
volume loss. The operator must configure the schedule and external destination.

Existing records are preserved; automatic deletion is disabled pending an explicit
retention decision. Resolved tickets, audit logs, and backups contain operational
metadata and must follow that decision. Disk-pressure alerts are provided. Never
silently purge user data to satisfy a storage target.

## Reference semantics

Probe behavior follows the [Kubernetes probe documentation](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/).
Container restrictions follow the [Kubernetes security-context documentation](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/).
