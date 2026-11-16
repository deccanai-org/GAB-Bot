---
title: Phase 6.1 QC reference - current rules and historical QC FAQ scope
audience: qc
phase: 6.1
updated: 2026-11-14
source: 'QC-FAQ.pdf, pages 5-8 (Phase 5 scope); Annotation- FAQ.pdf, pages 1-4; GAB Tasking Flow and Rating Methodology - v6.1.pdf, page 3; GAB - Production - Evaluation Guide - v6.1.pdf'
---

Q0. Does the supplied QC FAQ contain current Phase 6.1 model and recording rules?
The supplied QC FAQ labels its model and recording checklist as Phase 5 and retains older sections. Use the newer annotation FAQ, the Phase 6.2 update and the v6.1 production guides for current task requirements: Phase 6.2 is Model A only on 1p-old -> flash_1p_old_test_arm, with no Model B, other models or Reset (U1); no screen recording required; Gemini debug mandatory. Do not apply the older recording-based rejection instructions to Phase 6.1. Use EV1-EV16 for Stage 4 human evaluation.

Q1. Which models should be used for current tasks?
Phase 6.2: Model A only, 1p-old -> flash_1p_old_test_arm; no work on Model B or any other model (U1, U3). Check the selection before every message; a turn on the wrong model leads to task rejection under the current annotation FAQ. Phase 6.1 tasks used Product A GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm and Product B GPT-5.6 Terra High.

Q2. Can I use the older QC "Created with" model rule unchanged?
The QC PDF's model-specific "Created with" example is labelled Phase 5. For Phase 6.1, verify the actual required selection in Q1 and use the current task evidence. Ask your QM if the available metadata does not establish the model; do not assume a previous-phase display name is required.

Q3. What Gemini debug recipe ID is valid for current tasks?
Phase 6.2 requires 1p-old -> flash_1p_old_test_arm (Phase 6.1 used GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm), but the supplied documents do not publish a definitive recipe ID for either. Verify the required model and escalate an uncertain recipe mapping to your QM. The older QC recipe example is Phase 5-specific and cannot establish the current recipe.

Q4. Can I reject a task using only an incomplete public conversation link?
The supplied QC FAQ warns that public links may omit turns: verify the complete conversation while signed in to the assigned account before rejecting for missing content. Phase 6.2 tasking is Model A only (1p-old -> flash_1p_old_test_arm). Use the corresponding conversation JSON and uploaded files as supporting evidence.

Q5. Can I rely only on share links or JSON files for artefact evaluation?
No. Open and check the actual uploaded final artefacts against the intent, not merely the model's description. For conversation completeness, the QC FAQ also directs reviewers to verify the full conversation in the assigned accounts instead of relying on the public link alone.

Q6. Can previous conversations be deleted from the account?
No. Preserve existing conversation history. The current annotation FAQ says old chats are expected because accounts are reused, and the task should start in a new chat with the seed prompt.

Q7. Can the annotator reuse identical or near-identical prompts across both models?
This no longer comes up: Model B is not worked on, and Phase 6.2 is Model A only (U3). Each follow-up must still be written by the annotator against the model's own reply; the seed prompt itself must be pasted exactly.

Q8. Can I leave auto-rated justifications unchanged?
Write the justifications yourself in natural language, with specific evidence for the correct product. In Stage 4, keep scores outside the artefact check pre-filled; correct scores only as specified in EV2. Accepting a score does not remove the requirement to write its justification.

Q9. How should justifications be written?
Write 2-3 sentences per dimension, using specific evidence, the relevant L2 concept and why the score band fits. Describe only that product, use accurate turn citations, and do not copy generated assistance or text between dimensions. SxS is a separate comparison of both products. See EV11-EV15.

Q10. Which deliverables are required?
For Model A only (Phase 6.2): conversation share link, complete conversation JSON, Gemini debug JSON, final model-generated artefacts, turn count, key turn and its justification, and Conversation Context for Model A. No Reset ID and no Model B work (U1-U3). Screen recording is not required (removed in Phase 6.1).

Q11. Is screen recording required for current QC review?
No screen recording is required for Phase 6.1. The screen-recording checklist in the supplied QC PDF belongs to Phase 5 and is superseded for current tasking by the dated v6.1 production update and current annotation FAQ.

Q14. Should I reject a conversation just because the debug JSON shows null?
Not on that basis alone. The v6.1 methodology explains that broken conversations or generation failures can cause null debug. Read the Conversation Context notes and consider the reported failures, interruptions and limitations before deciding. Gemini debug submission and completeness checks are still mandatory for the annotator.

Q15. Should an annotator be penalised when a model takes over 25 minutes?
The supplied QC FAQ treats the timeout as a model-side issue rather than an annotator penalty. Check Conversation Context. The current annotation FAQ says to abandon a turn taking over 25 minutes and report it on the latency form. Reflect the evidence within the evaluation stage's permitted scope; Stage 4 scope is in EV2 and EV6.

Q16. Where do I report conversation generation delays or failures?
For current Phase 6.1 annotation, the form linked in the 14 Nov FAQ is https://forms.gle/hbRu5rbNwyzpqKqc7 . Record the issue in the affected product's Conversation Context as well. The older QC FAQ separately links https://forms.gle/KX1LrYzLb6Cb82KWA for its latency reports; confirm with your QM which form applies to your review stage.

## Current review checklist
<!-- summary: checklist, check list, before approving, before rejecting, qc checklist -->

Q19. Is there a checklist I should run before approving or rejecting a task?
- Check Model A was run on 1p-old -> flash_1p_old_test_arm (Phase 6.2), the complete conversation JSON, mandatory Gemini debug and final artefacts. No Model B work or Reset ID is expected (U1-U3).
- Read the Model A Conversation Context and verify full conversation evidence before rejecting for missing public-link turns.
- Do not require screen recordings for Phase 6.1.
- For Stage 4, verify artefact criteria and correct only affected scores; keep other scores pre-filled.
- Write 16 evidence-based justifications and a supported seven-option SxS preference and summary. See EV16.
