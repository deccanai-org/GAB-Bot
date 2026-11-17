---
title: Phase 7.1 updates - announcements and team answers (annotation)
audience: all
phase: 7
updated: 2026-11-17
source: 'GAB Phase 7 #announcements (Annotators, QC, Evaluation) and team answers in GAB Phase 7 Conversation Annotators #project-related-queries, 16-17 Nov 2026 (all 401 messages read 17 Nov 2026, 15:50 IST)'
---

## Models and thinking level

S1. What thinking level do I use? Which models are used in Phase 7.1 and 7.2?
Phase 7.1 compares two Gemini products. Product A: 3.5 Flash-Lite with Thinking level HIGH. Product B: 3.8 Flash-Lite (Model Underwing). Phase 7.2 (Gemini vs Claude) has not started yet; when it does, all its conversations use Haiku 5.5 Medium with the default Thinking Mode only. Use these configurations consistently.

S2. I can't find "3.8 Flash-Lite" for Model B, only "Flash-Lite -> Model Underwing". Is that right?
Yes. "Flash-Lite -> Model Underwing" is the correct Model B; it is shown that way in the screenshot in the instructions doc. Look for it in work mode.

S3. The task form shows the wrong model (3.8 for Model A, or asks for a Claude Haiku share link for Model B, or says "Add a valid Model B share link (claude.ai)"). What do I do?
Refresh the Cosmo platform page: the form was updated. In the form, tick the model checkbox and select the model the instructions name; any screenshot shared in the channel is only an example. Always follow the instructions doc: Model A is 3.5 Flash-Lite and Model B is 3.8 Flash-Lite -> Model Underwing, both Gemini. If you already ran a conversation on the wrong model, it's better to redo it.

S4. The model or thinking level changes back after every turn. What do I do?
Reload the page and try again. Before every turn, check that the right model and thinking level are selected, and set them back if they changed. If you set them back correctly before every turn, your task is fine. A thinking level (HIGH) is set only for Product A; the instructions give no thinking level for Product B, so for Model B just select 3.8 Flash-Lite (Model Underwing).

## Screen recording

S5. Do I record each model separately? When do I start and stop?
Screen recording is mandatory in Phase 7.1. Record each model separately. Start recording when you send your first prompt (the seed prompt) and stop only after the final model response. Keep recording while you type your prompts: the whole interaction must be recorded, and no interaction may be missed. Pause the recording when you switch tabs to look at the instructions or Cosmo. Keep recording for the whole model run, even if it takes 50 minutes or more. "First prompt" means the seed prompt, not a "What have we been working on?" check. If you recorded the entire screen instead of only the conversation tab, redo the recording.

S6. Which tool can I use to record the screen?
Any built-in recording tool of your computer is fine, for example Clipchamp or the Snipping Tool (Windows + Shift + R) on Windows, or Command + Shift + 5 on a Mac. Clipchamp is not required: any built-in tool is fine. Do not use external or third-party recording tools.

S7. My recording stopped at 30 minutes, or part of the conversation wasn't recorded. What do I do?
If the recording is in parts (for example, Clipchamp's 30-minute limit), merge the clips into one video before uploading. If part of the interaction was not recorded at all, that is not acceptable: redo the conversation and record it.

S8. Is a large recording file (about 1 GB) OK? Where do I upload it?
Yes, a file of about 1 GB is fine. Upload it in the screen recording field on the Cosmo platform; if you can't see the field, reload the page.

## Debug, conversation and artifacts

S9. Do I need a debug JSON for Model B too?
Yes. Debug generation is mandatory for both Product A (Model A) and Product B (Model B) in Phase 7.1. Use the same script for Model B. If the Model B debug upload field is missing, refresh the page.

S10. The debug info isn't produced for every turn. What do I do?
Retry, and don't refresh the page while the debug JSON is loading. Before uploading, check that the debug JSON has one entry for every turn.

S11. The model remembers my past conversations even with memory off. What do I do?
Proceed with the task in a fresh chat, and flag it in Conversation Context if the model brings up an earlier conversation during the current task. See S21 if it comes up when you ask "What have we been working on?".

S12. The model takes a very long time to respond. What do I do?
Wait up to 25-30 minutes for a response. If it takes longer, abandon the conversation, mention the issue in the Conversation Context field, report it with the latency reporting form (https://forms.gle/P3X3iib18ZnWMxta7), and start the conversation again from the beginning. In Conversation Context, mention delays, failures, errors or early termination; if there were no issues, enter NA. This is mandatory for both Product A and Product B.

S13. Can I copy prompts between Product A and Product B, or from the Turn Plan?
No. Do not copy-paste prompts between Product A and Product B, and do not copy-paste prompts directly from the Turn Plan. The only exception is the seed prompt, which is used as provided. Prompts must be written naturally by you and must not be LLM-generated.

S14. The model made something the intent didn't ask for (a slide, an interactive visual, audio). Do I upload it?
Yes, upload what the model generated as artifacts, even if the user intent didn't ask for it (for example, an interactive visual with stats). Upload audio as mp3. If an artifact was edited step by step, upload only the final version. A calendar invite that prints in IST instead of the user's time zone can be uploaded as it is.

S15. An artifact was saved straight to Drive and isn't visible in the conversation tab. Do I need to show it in the recording?
No. If it isn't visible in the conversation tab, you don't need to record it.

S16. Does the first time I ask for something count as a nudge?
Yes. The first ask is the first nudge, so you can try 2 more times: never nudge the model more than 3 times for a single intent.

S17. The persona is missing in my task. Can I continue?
Yes, you can proceed with the task.

S18. The Drive files don't match the prompt or the persona. What do I do?
Pause the task and report it to the team with your task (alloc) ID and test account, so they can check it.

S19. When do I get more tasks, and when does my task limit go up?
New tasks are assigned after your submitted task has been through QC; if the queue is empty, wait for new tasks on the platform. QC for Phase 7.1 runs after the annotation for the phase, so most contributors keep their initial number of tasks until then. A contributor's task limit is increased depending on the quality of their work. Keep checking the platform for feedback and reworks, and when you get feedback, check it carefully and verify the model's thinking level.

## Starting the conversation

S20. Do I ask "What have we been working on?" before the seed prompt?
It's optional. The instructions doc doesn't require it, so you can start straight with the seed prompt (see the "How to converse with the Models" tab). You may also ask it first as a memory check, as shown in the walkthrough video: ask it, then send the seed prompt in a fresh chat. Your screen recording starts at the seed prompt, so the memory check doesn't need to be recorded.

S21. I asked "What have we been working on?" and the model described earlier work. What do I do?
If what it describes is not related to the current task, leave that chat and start the conversation in a fresh chat. If it is related to the current task, proceed with the task in a fresh chat, and flag it in Conversation Context if the model brings up the earlier work during the current task.

## Thinking level and task status

S22. I submitted a task with Product A on thinking level LOW before the HIGH rule was announced. What happens?
Submissions made before 12:00 PM IST on 17 November that used thinking level LOW for Product A are sent back for rework (to you or another annotator) and the annotator is not penalized. Submissions after that time must use HIGH; LOW is penalized. Watch the platform for feedback and reworks.

S23. Has Phase 7.2 started?
Not yet. Phase 7.2 (Gemini vs Claude, Haiku 5.5 Medium) will start soon; the start will be posted in the announcements.

S24. My task was auto-skipped (for example, the timer ran out while it was paused). Can I get a new task?
Tasks come from the queue: when it is empty, you have to wait for new tasks on the platform. For your own task's status, contact the admin of this project.
