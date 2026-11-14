---
title: Phase 6.1 FAQ - Annotation
audience: annotator
phase: 6.1
updated: 2026-11-14
source: 'Annotation- FAQ.pdf, pages 1-4 (14 Nov 2026); GAB Instructions - Production - v6.1.pdf'
---

## Model selection

A1. Which model is Product A?
In the Gemini model picker, select GOAT-on-Thorin DTE (Gmail Fixes), then select flash_dte_test_arm. Verify that the selection worked before the first turn and check it before every message.

A2. Which model is Product B?
GPT-5.6 Terra High. Use the assigned test account and verify the model before every message.

A3. What happens if the wrong model is used or the model switches?
Switch it back to the right model before your next turn. Any turn run on a different model leads to task rejection. Check the picker before every message, not just after finishing.

A3b. How do I confirm the right model is selected?
Check the picker before the first turn and every subsequent message. Product A: GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm. Product B: GPT-5.6 Terra High.

## Accounts and environment

A4. What if files in Drive or Gmail are mismatched, irrelevant or missing?
Do not skip the task. Share your assigned test account and persona privately with the team so the environment can be fixed.

A5. I have a Google sign-in issue. Which email is needed for reset access?
Share privately with your manager the personal email you use to log in to the Deccan platform so environment reset access can be given. Use only that email for reset access. Conversation tasking itself uses the assigned persona test account.

A5b. When do I reset the environment?
Reset the environment after Product A and before Product B. Copy the resulting Reset ID into the tasking platform. See IN13 for the steps.

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
Use the scripts in the v6.1 instructions. Gemini downloads conversation.json and debug_info.json together; GPT downloads chatgpt_conversation.json only. Check every turn is present before uploading. GPT does not require a debug file.

## Turns and conversation conduct

A9. Where does the turn count start?
The seed prompt is Turn 1. Count from that prompt, and start the actual task in a new chat.

A10. How do I choose the key turn? Can it be Turn 1?
Choose the single turn of maximum synthesis, where the primary deliverable is generated or the intent is met. Usually it is not Turn 1. Select one per conversation and explain the choice in Key Turn Justification.

A18. Can I reuse the same follow-up prompts in Model A and Model B?
No. Cover the same turn plan but write each follow-up against that model's own reply. Do not reuse Model A prompts in Model B, even with a few words changed. Identical or near-identical prompts are treated as copy-paste and the task is failed.

A19. Can I copy the turn plan into my prompts?
No. It says what to ask, not how to say it. Write every follow-up in your own words, in the persona's voice. Only the seed prompt is pasted exactly.

A20. The model asks for something the intent does not specify. What do I say?
Tell it to check your files or go with what it suggests. Do not make up details such as your own time zone.

A21. How many times can I nudge the model?
Up to 3 times for each intent. If it still is not done, move on. A model failing is a valid result.

A22. How do I vary follow-ups naturally?
Include at least one very short turn under 10 words and one longer turn per conversation. Mix statements, short fragments and questions instead of starting every turn with "Can you" or "Please". Refer to specific output and rephrase recurring checks.

## Latency and context

A12. How long should I wait for a model to generate a turn?
Up to 25 minutes. If it takes longer, abandon the conversation, record the issue in that product's Conversation Context, and report it using https://forms.gle/hbRu5rbNwyzpqKqc7 .

A13. What goes in Conversation Context? What if nothing went wrong?
Record any delays, failures, errors, interruptions or stopping early. If there were no issues, enter NA. Fill the field for both products. Report latency issues using https://forms.gle/hbRu5rbNwyzpqKqc7 .

## Artefact uploads

A14. Should I upload every version of a refined artefact?
No. Upload each final artefact as an individual file. Do not upload intermediate versions. Calendar invites and Gmail drafts are uploaded as PDFs; everything else uses the format the model produced.

A23. The task asked for a Gmail draft but the model did not create it. What do I upload?
Nothing for that draft. The criterion is not met. Do not create an artefact yourself to replace the model's missing output.

## Pre-submission checklist
<!-- summary: checklist, check list, before submitting, before i submit, before submit, pre-submission, presubmission -->

A15. What is on the Phase 6.1 annotator pre-submission checklist?
- Product A: GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm; Product B: GPT-5.6 Terra High; checked before every turn.
- Memory off for both models; no previous chats deleted or brought into the current conversation.
- Seed pasted exactly; follow-ups written independently in your own words against each model's reply.
- Environment reset before Product B and Reset ID pasted.
- Gemini debug JSON has exactly the conversation's turns; both conversation JSONs include every turn.
- Key Turn, Key Turn Justification and Conversation Context filled for both products.
- Latency issues reported; only final artefacts uploaded; drafts and invites as PDFs.
- No screen recording is required for Phase 6.1.
