---
title: Phase 6.1 production instructions - account setup, conversations and exports
audience: annotator
phase: 6.1
updated: 2026-11-14
source: 'GAB Instructions - Production - v6.1.pdf, pages 1-21 and exporter guidance on pages 43-46 and 69-73; Annotation- FAQ.pdf, pages 1-4'
---

IN1. What changed for recording in Phase 6.1?
Effective 13 Nov 2026, no screen recording is needed for Phase 6.1. Gemini debug info remains mandatory. The current annotation FAQ dated 14 Nov confirms this; older recording pages retained in the PDFs are historical.

IN2. Which models are used in Phase 6.1?
Product A: GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm. Product B: GPT-5.6 Terra High. Verify the selection before every message.

IN3. How should I use the updated conversation guidance?
Read the whole intent before your first follow-up, use the turn plan as guidance and write naturally in the persona's voice. Start the actual task in a new chat with the seed prompt. Turn Memory off; never delete old chats or bring their content into the task. Report any old-chat reference in Conversation Context and tell your QM.

IN4. Update 02/11/2026: At the end of each conversation, fill in the Conversation Context field for Model A and Model B with any issues you ran into (for example the model taking more than 25 minutes to respond).

IN5. Which models do I use?
Model/Product A: select GOAT-on-Thorin DTE (Gmail Fixes), then flash_dte_test_arm. Model/Product B: GPT-5.6 Terra High. Check before the first turn and every message. If the model switches, switch it back before continuing; a turn on the wrong model leads to task rejection.

IN6. What are the steps of a task?
1. Set up: read the intent and opening (seed) prompt, log into the assigned test account, and take on the persona (student / educator / developer). Start the conversation with the seed prompt and continue it to achieve the final user intent as far as possible, using the Turn Plan follow-ups as guidance.
2. Model A: drive the full multi-turn conversation guided by the user intent. Capture the conversation link, the produced artefacts and the total turns. Convert the conversation to a .json file with the script in the instructions doc; the same script creates the debug file. Check that all turns are captured in the chat JSON and debug files.
3. Reset the environment and paste the Reset ID.
4. Model B: drive the full conversation the same way. Capture the link, artefacts and total turns. Convert the conversation to a .json file with the GPT script (no debug file is needed for GPT). Check that all turns are captured.
5. At the end of each conversation fill in, for Model A and Model B: Conversation Context (issues during generation, or NA), Key Turn, and Key Turn Justification.

IN7. What are the integrity rules?
- Window switching: only to reach the designated LLM tasking account. Switching windows for anything else is not permitted.
- Browser switching during a task is strictly prohibited.
- Write all follow-up prompts yourself. Do not use any LLM to create follow-up prompts.
- Do not use the tasking credentials for any personal work. Credentials are provided in the tasking window.
- Do not share the project Drive link with anyone.
- Do not copy project data from the Drive into personal spaces (personal drives, notes, devices, emails or chats).
- Any violation or suspicious activity may be flagged and can lead to strict quality action, including removal from the project.

IN8. Where do I get the account for the conversation?
In the tasking window: it gives the persona, email and password for the persona account. Open a new Chrome profile with those credentials, and use the same email to open Gemini and GPT for tasking.

IN9. Should memory be on?
No. Turn off "Memory" for each model before you start the conversation.

IN10. How do I connect Gemini to Google Workspace?
Profile icon (bottom left) -> "Personal Intelligence" -> "Connected Apps" -> turn the Google Workspace toggle on.

IN11. How do I connect ChatGPT to Google Workspace?
In the tasking environment described by the v6.1 instructions, click Plugins under the prompt bar, then Connect plugins, then the plus (+) next to each required Google application. Use the assigned persona account for ChatGPT, Gmail and Drive.

IN12. Do I need the GitHub connector?
No. All coding-related files are in the Drive folder of the persona's account.

IN13. How do I reset the environment?
1. Click Reset Environment.
2. Log in with the Deccan Experts ID used for the Cosmo platform.
3. Click reset and wait for completion.
4. Find the Reset ID at the bottom of the dialog.
5. Paste it into the platform's Reset ID field.
Reset after Model A and before Product B.

IN14. What counts as an artefact?
Files the model actually generated: images, videos, draft emails, calendar invites and Google Workspace/Drive files such as docs, sheets, slides and PDFs. Instructions or a description of how to build a file are not an artefact. A conversation link is the share link; produced artefacts are the actual generated deliverables.

IN15. How do I upload artefacts?
- Upload each artefact as an individual file. You do NOT need to make a zip file any more.
- Upload artefacts in the format the model produced them, except calendar invites and email drafts, which are uploaded as PDFs.
- Upload only final artefacts, not versions that were sent back to the model for rework.
- If the task needed a real draft in Gmail, the model should have created it, and only that draft is uploaded. If the model failed to create it, no upload is needed and the criterion is not met.
- In the "Did the model produce artifacts?" field, select Yes if any images, videos, draft emails, calendar invites or G-Suite/Drive files were generated; otherwise No.

IN16. How do I export the conversation JSON and debug file?
After completing the chat, right-click the chat, choose Inspect, open Console and run the approved script from the v6.1 instructions. If Chrome blocks pasting, type allow pasting and press Enter once for that profile, then paste the script. Gemini downloads conversation.json and debug_info.json together. GPT downloads chatgpt_conversation.json only; it needs no debug file. Keep the tab in front while the script runs.

IN17. Any tips for the Gemini script?
Run it in the same tab right after finishing the chat: the Debug Info disappears once the page is reloaded or the chat is reopened. Keep the tab in front while it runs, and click Allow if Chrome asks to allow multiple downloads.

IN18. What must I check in the JSON and debug files?
Both products' conversation JSONs must contain every turn. Gemini debug JSON must have exactly one entry per conversation turn, none missing and none extra. Run the Gemini script in the same tab immediately after the chat, before reloading or reopening it. The v6.1 GPT conversion section permits the fallback of using an LLM to generate the JSON if its script fails; check completeness yourself. This does not permit using an LLM to write conversation follow-ups.

IN19. How do I share the Gemini conversation link?
Open the sidebar (top left) -> find your chat under "All chats" -> click the three-dot menu -> "Share Conversation" -> "Copy link" under "Shareable public link" -> paste it into the portal.

IN20. How do I share the ChatGPT conversation link?
Click Share at the top right of the completed chat. In the v6.1 tasking walkthrough this creates a public conversation link and a confirmation dialog, with the link copied to the clipboard. Paste it in the corresponding task field.

IN21. Key turn: the single turn of maximum synthesis, where the primary deliverable is generated or the intent is met. Usually not Turn 1. One per conversation. Key turn justification: evidence of why that turn is the key turn.

IN22. Turns in the conversation: the total number of turns (counted from the seed prompt).

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

IN28. What do I fill in on the tasking platform?
Use the task prompt, user intent and assigned pre-seeded account. For both products submit the conversation share link, complete conversation JSON, produced-artifacts selection and final artefact files, total turns, Conversation Context, Key Turn and Key Turn Justification. Gemini additionally needs its debug JSON. Reset after Product A and paste the Reset ID before Product B. No screen recording is required for Phase 6.1.

IN29. Which playground tutorial videos are available?
The linked tutorials cover account setup, creating model conversations with task guidance, the tasking platform walkthrough, artefacts, reset, and debug/conversation JSON export. The supplied pre-assessment tutorials additionally cover task introduction, creating conversations, sharing metadata and performing evaluations. Use the Phase 6.1 FAQ for current models, ChatGPT tasking and the no-screen-recording rule when older recordings differ.

IN30. What is in conversation JSON, and what goes in artifacts?
Conversation JSON contains messages with role and text; assistant messages also have an artifacts field naming generated deliverables, or NA when none were generated. Check per-turn names against the actual files. Gemini and GPT use separate approved exporters. GPT reads actual tool records and page evidence for images, files, Canvas/Writing documents, Gmail drafts, Calendar events and Drive files. A claim to create a file is not by itself proof of an artefact.

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

IN35. How do I run the ChatGPT export script, and what does it produce?
Open the original chat on chatgpt.com, open F12 -> Console, allow pasting if prompted, paste the approved GPT script and press Enter. Keep the tab in front. It downloads chatgpt_conversation.json with per-turn artifacts and checks the page against ChatGPT's saved chat record. Original chats provide more checks than share links. It retries missing content and saves chatgpt_conversation_INCOMPLETE.json if completeness checks still fail. GPT needs no debug JSON.

IN35b. What does the ChatGPT exporter count as an artifact?
The v6.1 GPT exporter records generated images and edits, charts and files made by code, Writing/Canvas documents and later edits, Gmail drafts and emails, Calendar events, and Drive files made through ChatGPT apps. It reads the actual tool record and checks against the page. Plain reply text drafted for copying is not a generated Writing document. Declined, unapproved or failed actions do not establish a created artefact. If the record is unavailable, inspect the page-only warnings and verify every turn that produced something. Calendar events are enabled by default in this GPT exporter.

IN36. The ChatGPT script says No messages found, INCOMPLETE, or check the notes below. What should I do?
No messages found: open the ChatGPT conversation and wait for it to load. INCOMPLETE: inspect the reported missing prompts, unreadable messages or scrolling problem; reload, wait for loading and rerun the GPT script. Saved with notes: verify each warning, message count and per-turn artifact name against the original chat; page-only artifact checks are less complete when the saved record is unavailable. If the exporter stops unexpectedly, send the error to the script owner if retrying repeats it. For script failure, the document allows an LLM-generated JSON fallback, with every turn checked. Never reload the Gemini task tab before collecting its debug file.
