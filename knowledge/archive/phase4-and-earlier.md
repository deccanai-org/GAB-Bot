---
title: ARCHIVED - Phase 4 and earlier FAQs (annotation + QC)
audience: all
phase: 4
status: archived
note: The bot does NOT load files in knowledge/archive/. Kept for reference only. Model names here are OUT OF DATE.
---

## Phase 4 - Annotation (5 Nov 2026)

- Model: Product A = "GOAT-on-Thorin DTE (Gmail Fixes)", then select "ultra_carbon_dte_test_arm" before starting.
- Confirm the model name in the prompt bar before the first turn. Wrong model -> task can be rejected and reworked from scratch.
- Open and check the debug JSON for every task: every turn present, nothing null or empty.
- Conversation Context field (one for Model A, one for Model B): record any generation issue, or "NA". Report every generation issue on the Conversation Generation Issue form.
- Wait up to 25 minutes per turn; if longer, abandon, note it in the Conversation Context field, report it on the form.
- Model can't generate image/video after 2-3 nudges -> key turn 0 with justification.
- Turn count starts from the seed prompt; "What have we been working on?" is not a turn; run the main conversation in a new chat.
- Google sign-in issue -> share the personal email used on the Deccan platform for environment reset access.
- Upload only the final version of refined artefacts.
- Drive/Gmail files mismatched or missing -> don't skip; share test account and persona with the team.

## Phase 4 - Quality Check (6 Nov 2026)

- "Created with" field for Product A should show "GOAT-on-Thorin DTE (Gmail Fixes)" with ultra_carbon_dte_test_arm.
- Never leave auto-rated justifications unchanged; rewrite in a natural human voice.
- Sign in and verify the full conversation in both Claude and Gemini; don't rely on public links or JSON alone; check the chat was not reused after the public link was generated.
- Don't reject only because the debug JSON is null; check the Conversation Context fields first.
- Don't penalise the annotator for a 25-minute timeout; reflect it in the model's dimension criteria.
- Key Turn 0 where image/video was needed and the model (Claude Fable 5.1) lacked the tool, after 2-3 nudges.

## Earlier (general) FAQ - Annotation and QC

- Model: always select "GOAT-on-Thorin DTE (Ultra)".
- Otherwise same rules as Phase 4 (debug JSON, Conversation Context, 25-minute limit, key turn 0, seed prompt, final artefacts only).
