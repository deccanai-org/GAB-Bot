# Phase 6.1 source integration validation - 14 November 2026

This is historical evidence from before external providers were removed. See
[local-only validation](local-only-validation.md) for the current operating mode.

The five supplied PDFs are represented by 131 numbered text FAQ entries in eight
active documents. Playground answers add relevant links from the ten supplied
video URLs. Prior-phase knowledge is retained in the archive, excluded from
retrieval and Claude prompts.

| Check | Result |
| --- | --- |
| Full regression suite in the Git checkout | 259 passed; no failures or skips |
| Real local embedding evaluation | 40/40 passed; no critical failures |
| Python | 3.13.5, isolated workspace environment with the declared runtime dependencies |
| Lint, formatting and patch whitespace | Passed |
| Source review | All five PDFs extracted; key model/update and score/preference tables visually checked |
| Source traceability | SHA-256 recorded for all five PDFs and all 11 unique archive videos |
| Video links | All ten supplied links configured; model-generated URLs are never rendered |

The checks cover current model names, removal of the recording requirement,
Gemini debug completeness, separate GPT export, Stage 4 score-correction scope,
seven-option preference, independent follow-ups and playground stage selection.
They also cover role filtering, invalid URL rejection, catalog reload, and
existing transport/support behavior. The follow-up search replaces a single
previous product reference when the asker explicitly switches to the other
product, avoiding a mixed-product retrieval query.

Reports are in `artifacts/phase61-tests.xml` and `artifacts/phase61-eval.json`.
The embedding model was already cached; evaluation used offline mode. Claude
selection/rendering was checked with provider fakes, with no live provider calls.
Video access permissions and playback were not tested against the user's Drive
account. Videos were inventoried rather than transcribed; written solutions come
from the PDF guidance.

No registry push, cluster update, live Discord send or bot restart was performed.
Deploy/restart the updated application to activate the code changes in a running
instance. The existing phase-specific Discord channel configuration should be
checked against the intended server during rollout.

See [source import details](source-import-status.md) for document precedence and
the three archive recordings that use related supplied tutorials in lieu of a
direct video URL.
