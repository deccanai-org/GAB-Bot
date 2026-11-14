# Local release validation — 2026-11-14

The supported target is one Discord server and one active instance. This is a
locally validated release candidate. It has not been deployed or tested against
a live Discord server or external answer provider.

| Check | Observed result |
| --- | --- |
| Python | 3.11.18 |
| Lint and formatting | Passed |
| Tests, including real local embeddings | 262 passed, zero failures, zero skips |
| Statement coverage | 83.5% |
| Branch coverage | 72.3% |
| Retrieval evaluation | 65/67 passed; zero critical failures |
| Dependency audit | 86 installed packages; zero known vulnerabilities reported |
| Local search load | 100 requests, four workers; p95 0.063 seconds |
| Docker build | Passed |
| Docker smoke | Passed offline, non-root, read-only root filesystem, 1536 MiB and 1.5 CPU limits |

The retrieval misses were `qc-bad-recording` and `spec-nudges`. Both returned
partial answers requiring staff follow-up. The evaluator and its acceptance
threshold were preserved. These cases remain candidates for retrieval improvement.

Coverage is evidence of exercised paths, not a guarantee of correctness. The load
measurement exercises local search over four representative questions; it does
not measure Discord or external-provider latency. The dependency audit does not
cover OS packages in the container. No OS image vulnerability scan was completed.

Machine-readable evidence and input hashes are in
`artifacts/release-readiness.json`. The supporting JUnit, coverage, retrieval,
dependency-audit, and load reports are in `artifacts/`. These generated local
artifacts are intentionally ignored by source control.

Before a production rollout, complete the [operations runbook](operations.md):
run a separate test-server pilot, verify provider access if enabled, provision
secrets and persistent storage, test restoration and rollback on the target host,
and connect monitoring to an alert destination. Remote CI execution, an OS image
scan, and an off-volume backup schedule are still outstanding. Set a retention
policy explicitly; automatic deletion remains disabled.
