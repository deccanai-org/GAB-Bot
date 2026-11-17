---
title: Phase 6.2 updates - Model A only, refusals and queue
audience: all
phase: 6.2
updated: 2026-11-15
source: 'Bot queries-daily updated - Google Docs.pdf, page 1 (received 15 Nov 2026)'
status: archived   # superseded by Phase 7 (phase7-instructions.md), 17 Nov 2026
---

## Phase 6.2: Model A only

U1. What changes in Phase 6.2? Which model do I use?
In Phase 6.2 you work only on Conversation Generation for Model A. Model to use: 1p-old -> flash_1p_old_test_arm. Do not work on any Reset or other models, and do not make any changes related to Model B. Follow these instructions strictly: no work is carried out on Model B or any other model.

U2. Do I need to do a Reset or reset the environment in Phase 6.2?
No. In Phase 6.2, do not work on any Reset. Work only on Conversation Generation for Model A with 1p-old -> flash_1p_old_test_arm. The older step of resetting the environment between Product A and Product B no longer applies because Model B is not worked on. If files in Drive or Gmail are mismatched, irrelevant or missing, don't skip the task: see A4.

U3. Do I work on Model B? What if the task or Conversation Context still shows Model B?
No. Do not make any changes to Model B. Going forward, Model B will no longer be visible in upcoming tasks. Even if the Conversation Context field displays both Model A and Model B in the remaining tasks, work only on Model A: fill in the Conversation Context field with the relevant details for Model A only, then submit the task.

## Refusals and nudges

U4. The model gives a hard refusal (hard punt) and won't produce the output. What do I do?
Follow the 3 nudges rule. Example: the task asks for a photo of children in a classroom and the model says something like "I can't make a video that seems to show real minors...". If the model gives a hard refusal or does not generate the expected output, nudge it up to 3 times to guide it toward the intended result. If you still don't get the expected output after 3 attempts, move on to the next intent/turn and continue with the task.

## Task queue

U5. It says "Couldn't open the task" although I have two "limited throttle" tasks and there are tasks in the queue. What should I do?
Check the tasks available in the queue: all the tasks in the Annotation queue are currently Coding tasks rather than Generalist tasks. Advice for leads: move your strongest/HQ CBs to CQC.
