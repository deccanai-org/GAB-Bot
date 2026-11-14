---
title: Phase 5 FAQ - Quality Check (QC reviewers)
audience: qc
phase: 5
updated: 2026-11-08
source: 'QC-FAQ.pdf ("Phase 5 FAQ - Quality Check")'
---

## Model selection

Q1. Which models should have been used in Phase 5?
- Gemini test model: Flash, then Model Locust.
- Competitor model: Claude Sonnet 5.5 (High).

Q2. How do I check the model in the task?
Use the "Created with" field at the top of the task as the primary reference. For Product A it should show Flash. If an incorrect model is listed, reject the task. If no model is mentioned there, the prompt bar will not be visible in the shared link.

Q3. How do I check the model in the debug JSON?
Check the recipe ID in the debug JSON. For Locust you may see "gemini-v5s-rev27-geminiapp-chat-01-no-thought-summaries". The model ID can sometimes differ because of model routing for artifact generation, so a different model ID does not automatically mean the task is incorrect.

## Verifying the conversation

Q4. Can I review the conversation through the public link only?
No. Sign in to the respective Claude and Gemini accounts and open the provided links to verify the complete conversation. Public links sometimes fail to show all turns, so never reject a task without first checking the full conversation while signed in.

Q5. Can I rely on share links or JSON files alone?
No. Log in to the respective accounts and verify the task directly. Also check that the annotator did not reuse the same chat after generating the public link (for example, to ask the model for the Key Turn and its justification). Such conversations remain in the client's account and must be caught during QC.

Q6. Can previous conversations be deleted from the test account?
No. Do not delete any previous conversations. All existing conversation history must be preserved.

## Conversation naturalness

Q7. Can the annotator copy and paste the same prompt into both models?
No. Prompts must not be reused as-is or copy-pasted across Model A and Model B. Each follow-up must respond to that model's own reply. If the same prompts are reused, flag it in the annotator verdict.

## Justifications

Q8. Can I leave auto-rated justifications unchanged?
No. Review every justification thoroughly and correct it wherever issues are visible. This applies strictly to every QC task.

Q9. How should justifications be written?
In a natural, human-written manner. They must not read as LLM-generated or be copied directly from the auto-generated assistance justifications.

## Required deliverables

Q10. Which deliverables must be uploaded for each model?
The conversation link, the JSON PDF, the model-generated artefacts and the screen recording of the conversation. If any of these is missing for either model, flag it.

## Screen recording (QC)

Q11. What should I check in the screen recording?
- Scroll speed is moderate and steady, so the conversation is readable.
- All the turns are visible in the recording.
- The correct model was used in all the turns.
- Only the conversation page is visible in the recording.

Q12. What if the screen recording has any of these issues?
Reject the task and mention the screen recording issue clearly in the annotator verdict. During rush hours, redo the conversation and record it yourself; in that case set Annotator verdict: Fail and Action: Approve.

Q13. What if something was not screen recorded and it is flagged at the QC stage?
Report it as an edge case. Gemini conversations cannot be screen recorded at the QC stage because the debug will be gone.

## Debug JSON and conversation issues

Q14. Should I reject a conversation because the debug JSON shows null?
Not on that basis alone. Debug JSON can show null because of conversation breaks or generation failures. Before rejecting, check the Model A and Model B Conversation Context fields and consider any reported failures, interruptions or model limitations.

Q15. What if the annotator abandoned a conversation because the model exceeded the 25-minute limit?
Do not penalise the annotator. Treat it as a model-side issue: review the annotator's comments in the Conversation Context field and reflect the issue in the model's relevant dimension criteria during evaluation.

Q16. Where should conversation delays or failures be reported?
On the Latency Issue form. (Link not added to the bot yet - ask your manager or lead for it.)

## Key turn and turn count

Q17. When must the Key Turn be set to 0 for image or video generation?
When the task, or a major part of the user's intent, depends on image or video generation, the model has no tool to generate it, and the user nudged 2-3 times before moving on. Check these cases carefully and make sure the Key Turn value is 0.

Q18. Do we approve conversations that start with "What have we been working on?" instead of the seed prompt?
Yes, you can approve them. It is not best practice, though: annotators should ideally start the conversation from the seed prompt in a new chat.

## QC review checklist (Phase 5) - run before approving or rejecting every task
<!-- summary: checklist, check list, before approving, before i approve, before approve, review list -->

Q19. What is on the QC review checklist? (run through it before approving or rejecting every task)
- Correct models used in every turn (Gemini: Flash, then Model Locust; Competitor: Claude Sonnet 5.5 High)
- "Created with" field shows the correct model, and the debug JSON recipe ID was checked
- Signed in and checked the full conversation in both Claude and Gemini, not only the public link
- Same chat was not reused after the public link was generated
- Same prompt was not copy-pasted into both models
- No previous conversations deleted from the test account
- Conversation link, JSON PDF, model-generated artefacts and screen recording uploaded for both models
- Screen recording: slow and steady scroll, all turns visible, correct model in all turns, only the conversation page visible
- Screen recording issue mentioned clearly in the annotator verdict; in rush hours, conversation redone and recorded (Annotator verdict: Fail, Action: Approve)
- Model A and Model B Conversation Context fields reviewed before any rejection
- No rejection based only on null debug JSON
- Annotator not penalised for a 25-minute timeout; issue reflected in the model's dimension criteria
- Key Turn is 0 where image or video generation was needed and the model lacked the tool
- Every auto-rated justification reviewed, corrected and rewritten in a natural, human manner
