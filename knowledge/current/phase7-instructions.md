---
title: Phase 7 - GAB Dual Model Instructions (v7)
audience: all
phase: 7
updated: 2026-11-15
source: 'GAB Dual Model Instructions - v7 (Google Doc, important updates dated 15/11/2026; copy taken 17 Nov 2026), identical to GAB Instructions - Production - v7.1.pdf (knowledge/source-snapshots/gab-instructions-production-v7.1.txt)'
---

## Phase 7 updates: two models, reset and screen recording

V1. What changed in Phase 7? Which models do I use?
Phase 7 (GAB Dual Model Instructions v7, updates dated 15/11/2026) is a dual-model task: you run the same user journey on two models. Model/Product A: 3.5 Flash-Lite, with Thinking level HIGH. Model/Product B: 3.8 Flash-Lite -> Model Underwing. Select each in the Chat model picker and use only these models (see S1-S4 for the thinking level and model-picker questions). Using a different model leads to task rejection.

V2. What if the model keeps switching during the conversation?
Switching has been observed. Check the model before every turn, and if it has switched, switch it back to the right model (Model A: 3.5 Flash-Lite, Model B: 3.8 Flash-Lite -> Model Underwing) before you send the next turn. A different model in the conversation leads to task rejection.

V3. Is screen recording required in Phase 7?
Yes. Screen recording is required in Phase 7. Record the whole interaction with the model: start from the model selection step, so the selected model and Thinking Level are visible (announcement, 17 Nov 2026), and stop after the last model response. Record only the tab with the conversation, and upload the recording in the Screen Recording field. See V29-V31 for how to record.

V4. Do I reset the environment in Phase 7? Do I work on Model B?
Yes to both. Run Model A first, then reset the environment and paste the Reset ID in the tasking platform, then run Model B. See V20 for the reset steps.

## The task, start to finish

V5. What are the steps of a Phase 7 task?
1. Set up: read the user intent and the opening (seed) prompt, log into the assigned test account and take on the persona (student, educator or developer). Start the screen recording.
2. Model A (3.5 Flash-Lite): send the seed prompt and drive the full multi-turn conversation towards the user's final intent, using the Turn Plan follow-ups as guidance. Capture the conversation link, the produced artifacts and the total turns. Run the script to create the conversation .json and the debug file, and check that every turn was captured.
3. Reset Environment and paste the Reset ID.
4. Model B (3.8 Flash-Lite -> Model Underwing): drive the same journey the same way and capture the same items; the script downloads both the debug and the conversation file.

V6. How do I set up the account and browser?
The persona account (persona, email and password) is given in the tasking window. Open a new Chrome profile with those credentials, and use the same email address for both versions of Gemini. Turn off "Memory" for the model before you start the conversation. Tasking credentials are for tasking only, never for personal work.

V7. How do I connect Gemini to Google Workspace?
Click the profile icon in the bottom left corner, click "Personal Intelligence", click "Connected Apps", and turn the Google Workspace toggle on.

V8. Do I need the GitHub connector?
No. All coding and related files are in the Drive folder of the persona's account.

V9. What do I fill in at the end of each conversation?
For Model A and for Model B, fill in all three fields: Conversation Context, Key Turn and Key Turn Justification. Use Conversation Context to note any issues you ran into while generating the conversation (for example, the model taking more than 25 minutes to respond).

V10. What is the key turn and the key turn justification?
The key turn is the single turn of maximum synthesis, where the primary deliverable is generated or the intent is met. It is usually not Turn 1, and there is one per conversation. The key turn justification is the evidence for why that turn is the key turn.

V11. What do I submit for each model?
For each model: the public conversation share link; the conversation .json and the debug .json made with the script in the instructions; whether the model produced artifacts (yes if it generated any images, videos, draft emails, calendar invites or G-Suite/Drive files, else no) and, if yes, the artifact files; and the number of turns in the conversation.

V12. How do I upload artifacts? Do I need a zip file?
No zip file is needed: download and upload each file the model generated individually. Upload artifacts in the format the model provided, except calendar invites and email drafts, which are uploaded as PDFs. Upload only the final artifacts, not the versions sent back to the model for rework.

V13. What if the task needed a Gmail draft and the model didn't create it?
If the requirement was to create an actual draft in Gmail, the model should have done that, and only that draft is uploaded. If the model failed to create it, no upload is needed, and that criterion is not met.

V14. How do I get the conversation share link?
Click "Open Sidebar" in the top left corner of the chat, find your chat under "All chats", open its three-dot menu, choose "Share Conversation", then click "Copy link" in the "Shareable public link" box and paste it in the platform.

V15. How do I create the conversation .json and debug .json files?
Right after finishing the conversation, in the same tab: right-click the chat, click "Inspect", open the "Console" tab, paste the script from the instructions doc (Gemini exporter v2.0.0) and press Enter. It downloads conversation.json and debug_info.json together. Keep the tab in front while it runs, and click Allow if Chrome asks to allow multiple downloads. Debug Info disappears once the page is reloaded or the chat is reopened, so run it before that. Both models are Gemini, so upload a debug JSON for both.

V16. The console won't let me paste the script. What do I do?
Type "allow pasting" in the console and press Enter, then paste the script and press Enter. You only need to do this once per Chrome profile.

V17. What must I check in the debug JSON before uploading?
The turn counts must match: the debug JSON must have the same number of turns as the conversation, with one entry for every turn, none missing and none extra. Missing this leads to task rejection. Also check that every turn was captured in the conversation .json.

V18. What are the produced artifacts and the "Product" and "Link" fields?
Product means the two models: 3.5 Flash-Lite and 3.8 Flash-Lite -> Model Underwing. Link means the conversation share link. Produced artifacts are the files the model actually generated, such as sheets, slides and PDFs.

V19. Which compliance rules apply in Phase 7?
Switch windows only to reach the designated LLM tasking account; switching browsers during a task is not allowed. Write every follow-up prompt yourself, never with an LLM. Don't use the tasking credentials for personal work, don't share the project Drive link, and don't copy project data into personal drives, notes, devices, emails or chats. Any violation or suspicious activity can lead to strict quality action, including removal from the project.

V20. How do I reset the environment after the Model A run?
1. Click "Reset Environment".
2. Log in with the Deccan experts ID you use for the Cosmo platform.
3. In the dialog asking to reset the environment, click reset and let it run.
4. When the reset is done, find the "Reset ID" at the bottom of the dialog.
5. Copy the Reset ID and paste it in the "Reset ID" box in the tasking platform.

## Having the conversation

V21. How do I start the conversation with the model?
Send the seed prompt exactly as written (copy-paste it); that is Turn 1. Read the whole user intent before your first follow-up, then fulfil all of it as the persona, so that no intent, and no part of an intent, is left unattempted.

V22. How do I use the different parts of the user intent?
Unedited user goal: background only, never paste it to the model. Approach: how the person runs the conversation (e.g. "plan, then build"). Your voice: how the person writes; keep the same voice for the whole conversation, since switching midway fails the task. Goal: the outcome the whole conversation works towards. Turn plan: what to get across in each turn, in order; each line is an aim, not a script, so write your own message and try to stay inside the word range. "If..." lines: raise them only if that situation comes up. Expected outcome lines: use them to check answers, never say them to the model. Say when relevant: bring each point up once, when it fits, without pasting the wording. Stop when: end only once everything listed there is in place.

V23. How many times can I nudge the model?
No more than 3 times for each single intent. If it still isn't done after 3 nudges, move on: a model failing is a valid result.

V24. Can I use an LLM to write follow-up prompts?
No. All follow-up prompts must be written by you.

V25. How do I keep follow-ups varied and natural?
Vary length: include at least one very short turn (under 10 words) and one longer turn in each conversation. Vary the shape of the ask: not every turn needs "Can you / Could you / Please"; mix in plain statements, short fragments, a reaction before the ask, or a question back. Rephrase recurring checks differently each time, and anchor each turn on a specific line, number or section of the model's last reply. Don't paste the plan's wording: write what the persona would say.

V26. The model asks something the user intent doesn't answer. What do I say?
Don't make up details (for example, your own time zone). Tell the model to check your files, or to go with what it suggests.

V27. Do I reuse my Model A prompts for Model B?
No. Cover the same turn plan in Model A and Model B, but write each follow-up against that model's own reply.

V28. What should I never send to the model?
Only send what the persona would type. Never send tool or status text such as "Allow once" or "Continue the original task" as a prompt, and say "my Drive", not "the Drive of this account". Cover every ask in a turn: if a turn lists (a) and (b), your message must cover both.

## Screen recording

V29. What exactly do I record, and why?
Record the whole interaction with the model, from the model selection step (so the selected model and Thinking Level are visible; announcement, 17 Nov 2026) to the last model response. Record only the tab with the conversation, not the whole screen and not tab switches to Cosmo. The recording is used to understand the latency of model responses. Scroll at a moderate pace while reading long answers: quick scrolling suggests you are not reading the responses. Upload the recording in the Screen Recording field.

V30. How do I record only the conversation window on a Mac?
Press Command + Shift + 5, click "Record Selected Window", click the browser window with the conversation, then click Record. To stop, click the stop button in the menu bar or press Command + Control + Escape. Mac recording captures the whole browser window rather than a single tab, so keep the conversation in its own window.

V31. How do I record only the conversation tab on Windows?
Open Microsoft Clipchamp, choose "Create a new video", go to "Record & create" and choose "Screen". When asked to share your screen, choose the Chrome (or Edge) tab with the conversation and click Share. Click "Stop recording" when finished, then save or export the video.

## Tutorial videos

PG1. Where is the tasking walkthrough video?
The GAB Tasking Walkthrough video shows the tasking platform end to end. It is linked from the instructions doc.

PG2. Where is the introduction and account setup video?
The "Introduction and Account Setup" video gives an overview of the task and shows how to set up the environment.

PG3. Is there a video on how to have the conversation with the model?
Yes: "Creating Model Conversations With Task Guidance" shows how to use the user intent and turn plan to drive the conversation.

PG4. Is there a video on the debug and conversation JSON files?
Yes: "Debug and Conversation JSONs" shows how to run the script and download both files. Remember to check that the turn counts match (V17).

PG5. Is there a video on artifacts?
Yes: the "Artefacts" video explains what counts as an artifact and how to upload it (see V12).

PG6. Is there a video on resetting the environment?
Yes: the "Reset" video shows the reset after the Model A run (see V20 for the steps).
