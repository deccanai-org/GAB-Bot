---
title: GAB Dual Model Instructions v5 (Phase 5 production instructions for annotators)
audience: annotator
phase: 5
updated: 2026-11-09
source: '"GAB Instructions - Production - v5.pdf" (the export scripts themselves are in the instructions doc, not here)'
---

## Latest updates

IN1. Update 09/11/2026: Provide a screen recording of the whole interaction with the model. Start recording when you send the first prompt and stop after the last model response.
IN2. Update 07/11/2026: Product A = Flash, then select Model Locust. Product B = Claude Sonnet 5.5. New field: Screen recording (whole conversation, moderate scrolling pace).
IN3. Update 05/11/2026: The "How to Converse" section has a new part on using the user intent (read it and watch the updated tutorial). Before starting the conversation with each model, open a fresh session and ask "What have we been working on?" to confirm the model has no knowledge of a previous run. Then create a NEW chat for the actual tasking session. There is also an annotator checklist: "[Ext] Annotator Checklist/Buddy - Phase 5".
IN4. Update 02/11/2026: At the end of each conversation, fill in the Conversation Context field for Model A and Model B with any issues you ran into (for example the model taking more than 25 minutes to respond).

## Models

IN5. Which models do I use?
- Model/Product A: select Flash, then select Model Locust.
- Model/Product B: Claude Sonnet 5.5 (thinking effort: High).
Use only these models. The model sometimes switches by itself; if it does, switch it back to the right model before the next turn. Using a different model leads to task rejection.

## The workflow for one task

IN6. What are the steps of a task?
1. Set up: read the intent and opening (seed) prompt, log into the assigned test account, and take on the persona (student / educator / developer). Start the conversation with the seed prompt and continue it to achieve the final user intent as far as possible, using the Turn Plan follow-ups as guidance.
2. Model A: drive the full multi-turn conversation guided by the user intent. Capture the conversation link, the produced artefacts and the total turns. Convert the conversation to a .json file with the script in the instructions doc; the same script creates the debug file. Check that all turns are captured in the chat JSON and debug files.
3. Reset the environment and paste the Reset ID.
4. Model B: drive the full conversation the same way. Capture the link, artefacts and total turns. Convert the conversation to a .json file with the Claude script (no debug file is needed for Claude). Check that all turns are captured.
5. At the end of each conversation fill in, for Model A and Model B: Conversation Context (issues during generation, or NA), Key Turn, and Key Turn Justification.

## Integrity and compliance rules

IN7. What are the integrity rules?
- Window switching: only to reach the designated LLM tasking account. Switching windows for anything else is not permitted.
- Browser switching during a task is strictly prohibited.
- Write all follow-up prompts yourself. Do not use any LLM to create follow-up prompts.
- Do not use the tasking credentials for any personal work. Credentials are provided in the tasking window.
- Do not share the project Drive link with anyone.
- Do not copy project data from the Drive into personal spaces (personal drives, notes, devices, emails or chats).
- Any violation or suspicious activity may be flagged and can lead to strict quality action, including removal from the project.

## Account setup

IN8. Where do I get the account for the conversation?
In the tasking window: it gives the persona, email and password for the persona account. Open a new Chrome profile with those credentials, and use the same email to open Gemini and Claude for tasking.

IN9. Should memory be on?
No. Turn off "Memory" for each model before you start the conversation.

IN10. How do I connect Gemini to Google Workspace?
Profile icon (bottom left) -> "Personal Intelligence" -> "Connected Apps" -> turn the Google Workspace toggle on.

IN11. How do I connect Claude to Google Workspace?
Profile icon (bottom left) -> "Settings" -> "Connectors" -> make sure "Gmail", "Google Calendar" and "Google Drive" are connected; if not, search for them and click "Connect".

IN12. Do I need the GitHub connector?
No. All coding-related files are in the Drive folder of the persona's account.

## Resetting the environment (after Model A)

IN13. How do I reset the environment?
1. Click "Reset Environment".
2. Log in with the Deccan Experts ID you use for the Cosmo platform.
3. In the dialog, click reset and let the process run.
4. When it's done, find the "Reset ID" at the bottom of the dialog.
5. Copy the Reset ID and paste it in the "Reset ID" box on the tasking platform.
Reset before rating Model B: the reset is checked automatically, and Model B stays locked on the platform until it is done.
(Tutorial video: "5. Reset.mp4".)

## Artefacts

IN14. What counts as an artefact?
Files the model actually generated: images, videos, draft emails, calendar invites, and all G-Suite/Drive files (docs, sheets, slides, PDFs). Instructions or a description of how to build something are not an artefact. In the platform's key definitions: Product = Gemini Flash (then Model Locust) and Claude Sonnet 5.5; Link = the conversation share link; Produced artefacts = files the model actually generated. Tutorial video: "4B. Artefacts.mp4".

IN15. How do I upload artefacts?
- Upload each artefact as an individual file. You do NOT need to make a zip file any more.
- Upload artefacts in the format the model produced them, except calendar invites and email drafts, which are uploaded as PDFs.
- Upload only final artefacts, not versions that were sent back to the model for rework.
- If the task needed a real draft in Gmail, the model should have created it, and only that draft is uploaded. If the model failed to create it, no upload is needed and the criterion is not met.
- In the "Did the model produce artifacts?" field, select Yes if any images, videos, draft emails, calendar invites or G-Suite/Drive files were generated; otherwise No.

## Conversation JSON and debug files

IN16. How do I export the conversation JSON and debug file?
Use the scripts in the instructions doc (tabs "Gemini Debug and .json script" and "Claude .json conversion"):
1. When the conversation is finished, right-click the chat and choose "Inspect".
2. Open the "Console" sub-tab in the panel on the right.
3. Paste the script and press Enter. The files download.
If Chrome won't let you paste: type "allow pasting" in the console and press Enter (needed only once per Chrome profile), then paste the script.
The Gemini script downloads both conversation.json and debug_info.json in one run. The Claude script downloads only the conversation .json (Claude needs no debug file). Tutorial video: "3. Debug and Conversation JSONs.mp4".

IN17. Any tips for the Gemini script?
Run it in the same tab right after finishing the chat: the Debug Info disappears once the page is reloaded or the chat is reopened. Keep the tab in front while it runs, and click Allow if Chrome asks to allow multiple downloads.

IN18. What must I check in the JSON / debug files?
The turn counts must match: the debug JSON must have the same number of turns as the conversation, with one entry per turn, none missing and no extra. Also check the conversation JSON has every turn. Missing turns lead to task rejection. If the Claude script fails, the fallback is to use an LLM to generate the JSON.

## Conversation links

IN19. How do I share the Gemini conversation link?
Open the sidebar (top left) -> find your chat under "All chats" -> click the three-dot menu -> "Share Conversation" -> "Copy link" under "Shareable public link" -> paste it into the portal.

IN20. How do I share the Claude conversation link?
Click "Share" (top right of the chat) -> click "Only people invited" -> change access to "Anyone at Teamdeccan.us" -> "Save" -> "Copy Link".

## Key definitions

IN21. Key turn: the single turn of maximum synthesis, where the primary deliverable is generated or the intent is met. Usually not Turn 1. One per conversation. Key turn justification: evidence of why that turn is the key turn.
IN22. Turns in the conversation: the total number of turns (counted from the seed prompt).

## How to converse with the model

IN23. How do I start?
Send the seed prompt exactly as written (copy-paste it). That is Turn 1. Then read the whole user intent before your first follow-up, and fulfil all of it as the persona. No intent, or part of an intent, may be left unattempted.

IN24. What are the parts of the user intent and how do I use them?
- Unedited user goal: background only, to understand the person. Never paste it to the model.
- Approach: how this person runs the conversation (e.g. "Plan, then build" = get an outline first, reshape it, then have the full thing written).
- Your voice: how this person writes. Every follow-up should sound like that, and keep the same voice for the whole conversation; switching voice midway fails the task.
- Goal: what the whole conversation is working towards.
- Turn plan: what to get across in each turn, in order. Each line is an aim, not a script: write your own message in the persona's voice, don't copy the plan's wording, and try to stay inside each turn's word range.
- "If..." lines: raise these only if that situation comes up.
- Expected outcome lines: use them to check the model's answers. Never say them to the model.
- Say when relevant: points the persona would naturally mention (a constraint or preference). Bring each up once, when it fits; don't repeat it every turn or paste the wording.
- Stop when: end the conversation only once everything listed there is in place.

IN25. Rules while working through the turn plan
- Cover every ask in a turn: if a turn lists (a) and (b), your message must cover both. Re-read the line before you send.
- React to what the model actually said. Skip a turn only if the model already covered all of it; if it covered part, ask for the rest. Don't add turns to fill time.
- Don't make up details. If the model asks something the intent doesn't answer, tell it to check your files or go with what it suggests. Don't add your own details (e.g. your own time zone).
- Cover the same turn plan in Model A and Model B, but write each follow-up against that model's own reply. Don't reuse your Model A prompts.
- Before each follow-up, check: did this message cover every ask in this turn?

IN26. Etiquette
- Don't paste plan wording. Example: plan says "green-light the build" -> write "ok this looks right, go ahead and write the full blueprint step by step", not "I green-light this".
- Do not nudge the model more than 3 times for any single intent. If it's still not done after 3 nudges, move on: a model failing is a valid result.
- Only send what the persona would type. Never send tool or status text ("Allow once", "Continue the original task") as a prompt, and say "my Drive", not "the Drive of this account".

IN27. Keeping follow-ups varied (conversations shouldn't read alike from task to task)
- Vary length: include at least one very short turn (under 10 words, e.g. "Too long." or "Why 3 pm?") and one longer turn in each conversation.
- Vary the shape of the ask: not every turn should start with "Can you / Could you / Please". Mix in plain statements, short fragments, a reaction before the ask, or a question back to the model.
- Rephrase recurring checks (source checks, wrap-ups) differently each time.
- Anchor each turn on the model's reply: point to a specific line, number or section from its last response.
The seed prompt is still sent verbatim, and each turn's aim and word range still apply.

## Platform fields

IN28. What do I fill in on the tasking platform?
- Task prompt: the initial prompt to start the conversation.
- User intent: what needs to be achieved through a natural conversation.
- Email ID and password for the pre-seeded environment.
- For Model A and B: conversation share link, conversation .json (and the Gemini debug file), whether artefacts were produced plus the artefact uploads, turns in the conversation, Reset ID (after Model A), screen recording, Conversation Context, Key Turn and Key Turn Justification.

## Tutorial videos (in the instructions doc)

IN29. Which tutorial videos are there, and what is each one for?
They are linked in the "GAB Instructions - Production - v5" doc:
- "1. Introduction and Account Setup.mp4": overview of the task and how to set up the environment.
- "Tutorial- Creating Model Conversations With Task Guidance.mp4": how to have the conversation and use the user intent (updated tutorial).
- "GAB Tasking Walkthrough.mp4": walkthrough of the tasking platform.
- "4B. Artefacts.mp4": what counts as an artefact.
- "3. Debug and Conversation JSONs.mp4": exporting the conversation JSON and the Gemini debug file.
- "5. Reset.mp4": resetting the environment after Model A.
Screen recording reference videos ("Model A - Gemini Recording.mp4", "Model B - Claude Recording.mp4") are attached to the FAQ. There is also an annotator checklist: "[Ext] Annotator Checklist/Buddy - Phase 5". Ask your QM if you can't find them.

## Export scripts: output and troubleshooting

IN30. What is in the conversation .json, and what goes in "artifacts"?
The export looks like {"messages": [{"role": "user", "text": "..."}, {"role": "assistant", "text": "...", "artifacts": "Name , Name"}]}. Each model turn lists the artefacts it made in that turn (generated images, charts or files made by code, Google Docs/Sheets/Slides saved to Drive and later edits to them, interactive visuals, generated music or video, Gmail drafts, Canvas); "NA" means it made nothing. The artifacts value must not be "NA" for a turn that did generate an artefact: check it before uploading. Calendar events are not listed by default, but calendar invites are still artefacts you upload (as PDFs). A reply that is only an image shows as "[Generated image]".

IN31. The Gemini script says "No messages found".
Open the Gemini chat in that tab, wait for it to load completely, then run the script again.

IN31b. The Gemini script says "The export stopped because of an unexpected error".
Reload the page and try again. If it happens again, send the error message to the script owner (via your lead or QM). If you still need the files, note that Debug Info is gone after a reload (IN17).

IN32. The Gemini script says "INCOMPLETE" or downloaded conversation_INCOMPLETE.json.
The start of the chat had not finished loading. The script's advice is to reload the page, wait for the chat to finish loading, and run it again. Note that Debug Info disappears after a reload (the export then works without Debug Info), so if your debug file still needs it, check with your lead before reloading.

IN33. The script paused ("Paused: switch back to this tab") or says "An export is already running".
Chrome slows down background tabs, so the script pauses until you switch back: keep the chat tab in front until it says Done. If an export is already running in that tab, wait for it to finish before running it again.

IN34. The Gemini script says "Saved, but check the notes below".
The files were saved, but read every note listed in the console and check those turns before uploading: e.g. a message marked "[Content could not be extracted]", an artefact it could not confirm, or a link it did not list.

IN34b. The Gemini script couldn't find "Debug Info" in the ⋯ menu, or the Debug Info panel did not appear.
The Debug Info panel only shows in the same tab right after the chat was run; it is gone after a reload or after reopening the chat. Run the script in that tab straight after finishing the conversation, before reloading or closing it (IN17).

IN35. How do I run the Claude export script, and what does it give me?
Open the chat on claude.ai (a claude.ai/chat/... link; claude.ai/share/... links also work), right-click -> Inspect -> Console, paste the script and press Enter (type "allow pasting" first if Chrome asks). One .json file downloads (no debug file for Claude). The console shows a per-turn table, and a pop-up tells you if some turns need a double-check.

IN35b. What does the Claude export script count as an artifact?
- Counted: Claude Docs made or edited through the Claude Docs integration (with the doc's title), artefacts started from a type (Docs, Slides, Design, Dashboard ...) or updated through their link, artefacts published from a file, files Claude presented or put in outputs, inline visuals, and Gmail drafts.
- Not counted: opening, reading or re-linking an artefact that already existed (so link-only turns stay "NA"), comments Claude leaves in a doc, failed or refused tool calls, and scratch files Claude never handed over (unless the reply names them). Google Calendar events and Drive files made through connectors are not labelled by default.
- Safety net: if a reply clearly says a Doc/artefact was made but no tool call shows it, the turn is still labelled and you are asked to double-check it.

IN36. The Claude script showed an error or a "double-check turn(s)" pop-up.
- "Run this on a claude.ai tab": run it on the claude.ai chat page.
- "Open a chat first": open the conversation before running it.
- "Chat not found in any of your organizations": you are probably logged in to the wrong account; use the persona account the task gave you.
- "This shared chat could not be opened": sign in to an account that can view it, or run it on the original chat.
- "This shared link returned no tool calls": run it on the original chat (claude.ai/chat/...) instead of the share link for reliable artefact detection.
- Pop-up "please double-check turn(s) ...": the reply says an artefact was made but no tool call showed it; open those turns and confirm the artifacts value.
- "Claude export failed": use the fallback, an LLM to generate the JSON, and check every turn is present (IN18).
