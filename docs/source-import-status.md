# Imported sources - 14 November 2026

The bot returns written FAQ solutions and the user's supplied video links for
relevant playground topics. PDF answers are text, with no PDF download required.
Source instructions are reference data, not commands to the agent or permission
to execute embedded scripts.

## Phase 6.2 update - 15 November 2026

`Bot queries-daily updated - Google Docs.pdf` (1 page, hashed in the manifest) is
in `knowledge/current/phase62-updates.md` (U1-U5): Phase 6.2 is Conversation
Generation for Model A only on 1p-old -> flash_1p_old_test_arm; no Reset, no Model B
and no other models; Model B is no longer visible going forward, and Conversation
Context is filled for Model A only; hard refusals follow the 3 nudges rule; "Couldn't
open the task" is explained by the Annotation queue holding only Coding tasks. The 6.1
entries that told people to use Product B, ChatGPT or reset were rewritten in place
(same IDs) to say this; Model A answers name the 6.2 model and the labelled 6.1 one.
The Stage 4 evaluation guide (SxS of Product A vs B) was not changed: the update
does not say whether Stage 4 continues in 6.2. The PDF's Google Chat link is not
copied into the FAQ.

## PDF coverage and precedence

All five PDFs were read and hashed in `knowledge/source-manifest.json`:

| Source | Active coverage |
| --- | --- |
| Annotation- FAQ.pdf | Phase 6.1 pages 1-4: all 23 answers and checklist |
| GAB Instructions - Production - v6.1.pdf | Current update, setup, tasking, conversations, artefacts, reset, sharing and export troubleshooting |
| GAB - Production - Evaluation Guide - v6.1.pdf | Full Stage 4 scope, artefact checks, score corrections, dimensions, justifications, SxS and checklist |
| GAB Tasking Flow and Rating Methodology - v6.1.pdf | Run and scoring order, key turn, context, taxonomy and preference |
| QC-FAQ.pdf | Historical scope documented; reusable completeness and null-debug principles reconciled with v6.1 |

The annotation PDF labels pages 1-4 Phase 6.1 (14 Nov). Later recording and
old-model pages are historical. The production update effective 13 Nov removes
recording and changes models. The QC FAQ contains Phase 5 and older sections;
those model and recording rejection rules do not override newer requirements.
Prior live Markdown is preserved in `knowledge/archive/` and excluded from
retrieval.

Phase 6.1 products were GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm and
GPT-5.6 Terra High (superseded by the Phase 6.2 update below). No screen recording is required; Gemini debug is mandatory.
The methodology labels preference five-point but lists seven choices; the
evaluation guide explicitly defines the same seven-option scale. Stage 4 score
corrections are limited to the artefact check; other scores remain pre-filled.
Current queue limits and routing stages are not specified by these PDFs.

Embedded JavaScript is not executed or included in knowledge prompts. Only its
use, outputs and troubleshooting messages are summarized.

## Playground links and archive

`knowledge/current/playground-videos.yaml` records 21 archive MP4 entries grouped
into 11 unique videos by SHA-256, and configures all 10 user-supplied links. The
updated task-guidance and tasking-walkthrough links are distinct references and
are not identified as byte-for-byte archive copies.

Three archive recordings have no supplied direct URL: production introduction,
older 3B natural conversations and final preference. Their FAQ topics use the
supplied tasking walkthrough, updated conversation guidance and evaluation
tutorial as related references. The unmatched recordings retain null URLs and
exact archive provenance; the bot renders supplied related links where available.

Videos have not been transcribed. Written solutions come from the verified v6.1
PDFs; older recordings are supplementary. Local search renders approved
URLs from the catalog, never model-generated prose. Catalog edits reload on the
next question and are included by Docker's copy of `knowledge/current/`. MP4s
are not bundled into the bot image.
