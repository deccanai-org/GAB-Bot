---
title: Phase 6.1 FAQ - Annotation
audience: annotator
phase: 6.1
updated: 2026-11-14
source: 'Annotation- FAQ.pdf, pages 1-4 (14 Nov 2026); GAB Instructions - Production - v6.1.pdf'
---

## Model selection

A1. Which model is Product A?
Phase 6.2: in the model picker, select 1p-old -> flash_1p_old_test_arm (see U1). Verify that the selection worked before the first turn and check it before every message. Phase 6.1 tasks used GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm.

A2. Which model is Product B?
None. Do not work on or make any changes to Model B: it will no longer be visible in upcoming tasks. Work only on Model A (Phase 6.2: 1p-old -> flash_1p_old_test_arm). See U3.

A3. What happens if the wrong model is used or the model switches?
Switch it back to the right model before your next turn. Any turn run on a different model leads to task rejection. Check the picker before every message, not just after finishing.

A3b. How do I confirm the right model is selected?
Check the picker before the first turn and every subsequent message. Phase 6.2 Model A: 1p-old -> flash_1p_old_test_arm. Do not use Model B or any other model.

## Accounts and environment

A4. What if files in Drive or Gmail are mismatched, irrelevant or missing?
Do not skip the task. Share your assigned test account and persona privately with the team so the environment can be fixed.

A5. I have a Google sign-in issue. Which email is needed for reset access?
Reset access is not needed in Phase 6.2: do not work on any Reset (U2). Conversation tasking uses the assigned persona test account from the tasking window. The current FAQ gives no other fix for a sign-in problem: ask your QM or lead.

A5b. When do I reset the environment?
You don't in Phase 6.2: do not work on any Reset, and work only on Model A (U1, U2). The older step of resetting between Product A and Product B no longer applies because Model B is not worked on.

A6. Can I delete previous conversations from the test account?
No. Never delete any conversation. Accounts are reused from previous phases, so old chats are expected. Open a new chat and start with the seed prompt.

A6b. What if the model refers to an old conversation?
Turn off Memory and make sure nothing from previous chats is brought into the current conversation. If it happens, record it in Conversation Context and tell your QM. Do not delete the old chats.

A16. Which account do I use for Gemini, ChatGPT, Gmail and Drive?
Use the test account given in the tasking window in a new Chrome profile, with the same assigned email for all four services. Never use a personal or Deccan account for generating the conversations.

## Debug JSON and recordings

A7. What must I check in the Gemini debug JSON?
Debug info is mandatory for Gemini. Its turn count must match the conversation exactly: one entry per turn, none missing and none extra. Run the approved script in the same tab immediately after the chat ends, before reloading or reopening the conversation because Debug Info disappears. Check the file before uploading. For QC decisions involving null debug caused by a broken session, see Q14.

A8. Do I need a screen recording for Phase 6.1?
No. Screen recording is not needed for Phase 6.1. Debug info is mandatory instead. The older recording pages retained later in the FAQ PDF do not override the Phase 6.1 answer dated 14 Nov 2026 or the production update effective 13 Nov.

A17. How do I make the conversation JSON for each model?
Use the approved Gemini script in the v6.1 instructions: it downloads conversation.json and debug_info.json together. Check every turn is present before uploading. Phase 6.2 is Model A only, so no ChatGPT conversation JSON is needed.

## Turns and conversation conduct

A9. Where does the turn count start?
The seed prompt is Turn 1. Count from that prompt, and start the actual task in a new chat.

A10. How do I choose the key turn? Can it be Turn 1?
Choose the single turn of maximum synthesis, where the primary deliverable is generated or the intent is met. Usually it is not Turn 1. Select one per conversation and explain the choice in Key Turn Justification.

A18. Can I reuse the same follow-up prompts in Model A and Model B?
This no longer comes up: Model B is not worked on, and Phase 6.2 is Model A only (U3). Write every follow-up yourself against the model's own reply, in the persona's voice (A19).

A19. Can I copy the turn plan into my prompts?
No. It says what to ask, not how to say it. Write every follow-up in your own words, in the persona's voice. Only the seed prompt is pasted exactly.

A20. The model asks for something the intent does not specify. What do I say?
Tell it to check your files or go with what it suggests. Do not make up details such as your own time zone.

A21. How many times can I nudge the model?
Up to 3 times for each intent. If it still is not done, move on. A model failing is a valid result. The same applies to hard refusals (U4).

A22. How do I vary follow-ups naturally?
Include at least one very short turn under 10 words and one longer turn per conversation. Mix statements, short fragments and questions instead of starting every turn with "Can you" or "Please". Refer to specific output and rephrase recurring checks.

## Latency and context

A12. How long should I wait for a model to generate a turn?
Up to 25 minutes. If it takes longer, abandon the conversation, record the issue in that product's Conversation Context, and report it using https://forms.gle/hbRu5rbNwyzpqKqc7 .

A13. What goes in Conversation Context? What if nothing went wrong?
Record any delays, failures, errors, interruptions or stopping early. If there were no issues, enter NA. Fill it in for Model A only, even if the field shows both Model A and Model B (U3). Report latency issues using https://forms.gle/hbRu5rbNwyzpqKqc7 .

## Artefact uploads

A14. Should I upload every version of a refined artefact?
No. Upload each final artefact as an individual file. Do not upload intermediate versions. Calendar invites and Gmail drafts are uploaded as PDFs; everything else uses the format the model produced.

A23. The task asked for a Gmail draft but the model did not create it. What do I upload?
Nothing for that draft. The criterion is not met. Do not create an artefact yourself to replace the model's missing output.

## Pre-submission checklist
<!-- summary: checklist, check list, before submitting, before i submit, before submit, pre-submission, presubmission -->

A15. What is on the annotator pre-submission checklist?
- Phase 6.2: Model A only, on 1p-old -> flash_1p_old_test_arm, checked before every turn. No Model B, no other models, no Reset.
- Memory off; no previous chats deleted or brought into the current conversation.
- Seed pasted exactly; follow-ups written in your own words against the model's reply.
- Gemini debug JSON has exactly the conversation's turns; the conversation JSON includes every turn.
- Key Turn, Key Turn Justification and Conversation Context filled for Model A only.
- Latency issues reported; only final artefacts uploaded; drafts and invites as PDFs.
- No screen recording is required (removed in Phase 6.1).
