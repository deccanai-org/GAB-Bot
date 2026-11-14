# Local-only FAQ answering and usage limits

External model providers are disabled by explicit user instruction. The external
provider implementation was removed; settings reject external engines. Only
approved predefined FAQ answers and video links are returned. The local embedding
model reads preloaded weights with `local_files_only=True`; ONNX telemetry is off.
Unmatched and uncertain questions follow the existing human escalation path.

Defaults: 20 FAQ attempts per rolling 24 hours per user, 3 per minute across
channels, 1,500 question characters, four history messages of up to 400 characters,
and 6,000 answer characters. Limits are enforced before lookup; quotas persist in
`output/model_usage.sqlite3`, are reserved atomically, and are backed up with other
state. Failures count; local greetings and direct staff action/payment routing do
not. Overlong answers escalate without posting a truncated solution or URL.

Questions, history and FAQ contents stay within the bot's approved infrastructure.
No external model API keys are used. Existing Discord/Slack transport and approved
Git hosting remain separate from model inference. Pattern-based secret scrubbing
and audience restrictions remain active; these controls are tested, without
claiming that every possible secret format can be recognized automatically.

The previous provider cost estimate does not apply to this implementation.
External inference cost is zero; normal hosting and local compute still apply.

Validation reports are written to `artifacts/local-only-tests.xml` and
`artifacts/local-only-eval.json`. Prior Phase 6.1 validation predates the removal
of external providers; it remains historical evidence.

Final checks: 254 tests passed with no skips; all 40 retrieval evaluation cases
passed; 100 local requests through four workers had p95 latency of 0.072 seconds.
The offline test blocked Python network connections while loading the local
embedding model and answering a real FAQ question. Lint and formatting passed.
