---
title: Playground video help - tasking, exports, resets and evaluation
audience: all
phase: 6.1
updated: 2026-11-14
source: 'Playgrounds-20261114T165201Z-1-001.zip (inventory); supplied video links; Annotation- FAQ.pdf pages 1-4; GAB Instructions - Production - v6.1.pdf pages 1-21; GAB - Production - Evaluation Guide - v6.1.pdf pages 1-6'
status: archived   # superseded by Phase 7 (phase7-instructions.md), 17 Nov 2026
---

## Production playground tutorials

PG1. Which playground video introduces production tasking, and what are the steps?
The supplied tasking walkthrough supports this workflow: read the intent and seed, set up the persona account, complete Model A, export conversation and debug JSON, and collect its link and final artefacts. Record turns, Conversation Context, Key Turn and Key Turn Justification for Model A. The walkthrough's reset and Model B steps do not apply in Phase 6.2 (U1-U3). No screen recording is needed for Phase 6.1; Gemini debug is mandatory. See IN6, IN28 and A8. The archive also contains a separately titled production introduction.

PG2. Where is the account setup playground video, and how do I set up my account?
Use the persona account from the tasking window in a new Chrome profile, with the same assigned email for Gemini, Gmail and Drive. Turn Memory off. Enable Google Workspace in Gemini Connected Apps. No GitHub connector is needed. Phase 6.2 is Model A only on 1p-old -> flash_1p_old_test_arm; no Model B (U1). Apply these current settings when older recordings differ. See IN5, IN8-IN10 and IN12.

PG3. Where is the creating natural conversations playground video?
Send the seed prompt exactly as written as Turn 1. Read the full user intent and write your own follow-ups in the persona's voice, responding to the model's actual output. Use each turn-plan line as an aim, cover every ask, and avoid pasting the plan or unedited user goal. Do not use an LLM to write follow-ups, and do not nudge more than three times for one intent. See IN23-IN27 and IN7.

PG4. Where is the debug and conversation JSONs playground video, and how do I export the files?
Open Inspect -> Console in the same completed-chat tab and run the approved v6.1 script. Gemini downloads conversation.json and debug_info.json. Export Gemini before reloading or reopening the chat because debug information disappears. Every conversation turn must be present, with exactly one Gemini debug entry per turn, none missing or extra. See IN16-IN18 and A7; script troubleshooting is in IN31-IN36. QC's null-debug review rule is separately covered by Q14.

PG5. Where is the artefacts playground video, and which files do I upload?
An artefact is a file the model actually generated, including images, videos, draft emails, calendar invites and Google Workspace files. A description of how to create a file is not an artefact. Upload each final artefact individually in its produced format; upload email drafts and calendar invites as PDFs. Do not upload intermediate versions or make a ZIP. Check the produced-artifacts field and the per-turn artifacts values match what was actually generated. See IN14-IN15, IN30 and A14.

PG6. Where is the reset playground video, and how do I reset before Model B?
You don't need it in Phase 6.2: do not work on any Reset, and Model B is not worked on (U1-U3). The reset video covered the older Phase 6.1 step between Product A and Product B.

PG7. Where is the criteria and dimensions evaluation playground video, and how do ratings work?
Keep binary criterion decisions separate from the eight L1 ratings on the 1-5 scale. L2 concepts guide ratings and are not scored separately. A 5 means fully met without meaningful problems; 4 minor issues; 3 a meaningful issue needing correction; 2 major problems; 1 failure or a serious reliability or safety problem. Write specific evidence-based justifications. In Stage 4, check artefact criteria, correct affected scores only and accept everything outside that check as pre-filled. See RR1-RR4, EV1-EV12 and Q8-Q9. Apply current rules alongside older recordings.

PG8. Where is the final preference and justifications playground video, and how do I justify the preference?
Choose one of seven SxS options, from Product A significantly better through No clear preference to Product B significantly better. Compare concrete evidence from both in 2-3 sentences, explaining deciding dimensions, strength, and any preference opposing ratings or pass counts. Do not copy a dimension justification. See EV13-EV15 and Q9. The linked evaluation tutorial supports this topic; the archive also has a final-preference recording labelled "300 tasks version". Apply current v6.1 rules when older recordings differ.

## Pre-assessment playground tutorials

PG9. Which playground video introduces pre-assessment tasking?
The archive includes a pre-assessment introduction alongside a separate production introduction. Use the introduction for the stage you were assigned. For the current production workflow, follow PG1 and IN6; the presence of a pre-assessment recording does not change the current model, submission or QC requirements. The walkthrough title is an archive reference, and the current FAQ supplies the production guidance.

## Pre-assessment conversation exercise
<!-- summary: pre-assessment, pre assessment, preassessment -->

PG10. Which video should I watch before the pre-assessment conversation exercise?
Use the pre-assessment natural-conversations recording for that stage. The approved current conversation guidance is to send the seed verbatim, write follow-ups yourself in the persona's voice, respond to actual model output and attempt every part of the intent. For production, use PG3 and IN23-IN27 alongside the production-stage instructions.

## Sharing metadata tutorial

PG11. Where is the sharing the conversation playground video, and how do I get a share link?
For Gemini, open the sidebar, find the chat under All chats, open its three-dot menu, choose Share Conversation and copy the Shareable public link into the portal. See IN19. ChatGPT links are not needed in Phase 6.2 (Model A only). The supplied sharing-metadata video is a pre-assessment reference; follow the current FAQ if its screens differ.
