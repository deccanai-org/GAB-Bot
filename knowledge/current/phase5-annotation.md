---
title: Phase 5 FAQ - Annotation
audience: annotator
phase: 5
updated: 2026-11-08
source: 'Annotation-FAQ.pdf ("FAQ - Annotation 8 Nov 2026")'
---

## Model selection

A1. Which model is Product A?
The Gemini test model. Select "Flash", then select "Model Locust".

A2. Which model is Product B?
Claude Sonnet 5.5.

A3. What happens if the wrong model is used?
The task can be rejected and may need to be redone from scratch. Check the model before the first turn, not after.

A3b. How do I confirm the right model is selected?
Check the model name shown in the model picker / prompt bar before the first turn, and keep an eye on it during the conversation: the model sometimes switches by itself, so switch it back before the next turn (IN5). Product A: Flash, then Model Locust. Product B: Claude Sonnet 5.5 (thinking effort High).

## Test accounts and environment

A4. What if the files in Drive or Gmail are mismatched, irrelevant or missing?
Don't skip the task. Share your test account and persona with the team so it can be fixed.

A5. I'm facing a Google sign-in issue. What should I do?
Share the personal email you use to log in to the Deccan platform with the team so environment reset access can be given. Don't use any other email. (Share it privately with your manager, not in a public channel.)

A5b. Environment reset
Reset the environment before starting Product B (it is on the pre-submission checklist).

## Conversation history

A6. Can I delete previous conversations from the test account?
No. Do not delete any previous conversations from the test account. Keep all existing conversation history.

A6b. The model remembers a previous conversation in the fresh-session check ("What have we been working on?"), even in a new chat. What should I do?
Update 08/11/2026 (team answer on Discord): make sure Memory is turned off (IN9). Do not delete the previous conversations; you can still continue. Start the task in another new chat, and tell the team if the model refers to the previous conversation during the task.

## Debug info and screen recording

A7. What do I need to do with the debug info? Can I submit if a turn's debug info is null, empty or missing?
Copy and paste it for ALL turns, and make sure no turn is missing, null or empty. Missing or invalid debug info can get the task rejected.

A8. Do I need a screen recording?
Yes. Start recording when you enter the first prompt and keep recording the entire conversation until the model gives its final response. Once the chat generation is complete, upload the full screen recording to the platform along with the corresponding JSON files. Only the chat window should be visible; do not capture other applications, websites or desktop activity; scroll slowly and steadily; capture the entire generated conversation. (See the screen recording guidelines for full details.)

## Turn count and key turn

A9. Where does the turn count start?
From the seed prompt. If you ask "What have we been working on?", do it in a separate chat; it is not counted as a turn. The main conversation should start from the seed prompt in a new chat.

A10. Can the key turn be Turn 1?
Ideally not. Pick the turn where the main deliverable is generated, and justify it in one sentence.

A11. What if a model can't generate an answer (such as an image or video) even after nudging?
Nudge it 2-3 times. If it still fails, mark the key turn as 0 and explain why in the justification (state that the model could not generate the answer after 2-3 nudges and briefly describe what it failed to do).

## Latency and generation issues

A12. How long should I wait for a model to generate a turn?
Up to 25 minutes per turn. If it takes longer: abandon the conversation, note it in the Conversation Context field for that model (state clearly that it exceeded the 25-minute limit and was abandoned), and report it on the Latency Issue form.

A13. What goes in the Conversation Context field, and what do I write if nothing went wrong?
Any issue a model had during generation: unusually long generation, failures, errors or interruptions, stopping early, not completing due to limitations, or other unexpected behaviour. If there were no issues, enter "NA". Fill it for BOTH products (Model A and Model B), and report every latency or generation issue on the Latency Issue form.
Latency Issue form link: not added to the bot yet - ask your manager or lead for the link.

## Uploading artifacts

A14. Should I upload every version of a refined image or document?
No. Upload only the final version. Do not upload intermediate versions.

## Pre-submission checklist (Phase 5 annotators)
<!-- summary: checklist, check list, before submitting, before i submit, before submit, pre-submission, presubmission -->

A15. What is on the annotator pre-submission checklist? (run through it before submitting every task)
- Product A on Flash -> Model Locust; Product B on Claude Sonnet 5.5
- Environment reset before Product B
- Debug info copied for all turns, none missing or empty
- Screen recording of the whole conversation (chat window only) uploaded with the JSON files
- Turn count starts from the seed prompt
- Conversation Context filled for both products (issue, or NA)
- Latency issues reported on the form, if any
- Any key turn marked 0 has a justification
- Only final artifacts uploaded
- No previous conversations deleted from the test account
