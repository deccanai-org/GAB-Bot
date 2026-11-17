---
title: Phase 6.2 Conversation QC checklist
audience: qc
phase: 6.2
updated: 2026-11-16
source: 'GAB Conversation QC v6.2 (Google Doc, updated iteratively; copy taken 16 Nov 2026): https://docs.google.com/document/d/1phCADDn4s8BJg3MKCbjl0qvpBq6I9k_sYSwRJDJCvTA/edit?usp=sharing; Project GAB QC announcement forwarded 16 Nov 2026'
status: archived   # superseded by Phase 7 (phase7-instructions.md), 17 Nov 2026
---

## Phase 6.2 Conversation QC

CQ0. Where is the latest Phase 6.2 Conversation QC checklist?
The GAB Conversation QC v6.2 doc: https://docs.google.com/document/d/1phCADDn4s8BJg3MKCbjl0qvpBq6I9k_sYSwRJDJCvTA/edit?usp=sharing . It is updated over time; if it differs from these answers, follow the doc. The annotation instruction doc for this phase is GAB Instructions - Production - v6.2.

CQ1. How do I rate a task in Phase 6.2 Conversation QC?
Fix any minor errors in the task, such as key turn mismatches. So that proper feedback reaches the annotator, rate the task on a scale of 1 to 3:
- 3 - Perfect: no issues; the task meets all requirements.
- 2 - Minor Issues: minor edits required or missing artifacts.
- 1 - Major Issues: significant issues with conversation generation.

CQ2. What are the basic checks in Phase 6.2 Conversation QC?
If anything here is missing, send the task back to the SAME annotator:
- Public share link for Model A.
- conversation.json, with a turn count that matches the conversation. No Model B conversation is generated in Phase 6.2.
- debug_info.json for Gemini: every turn must have debug info (mandatory).
- All final artifacts uploaded as separate files (email drafts and calendar invites as PDFs).
- Screen recording: NOT needed in Phase 6.2.
Debug info is lost if the chat page is reloaded. If it cannot be recovered, treat the task as a redo.

CQ3. What are the conversation checks in Phase 6.2 Conversation QC?
If any of these fails, the task is REDONE by ANOTHER annotator:
- Correct model: Model A = 1p-old -> flash_1p_old_test_arm.
- Seed prompt sent exactly as Turn 1.
- Full user intent covered; "Stop when" conditions met.
- Follow-ups written in the annotator's own words and persona voice: no copied plan wording, no LLM prompts, no made-up details.
A model failing the task is acceptable: do not fail the annotator for model failures.

CQ4. Who gets the task back after Conversation QC? What is the task reassignment matrix?
- Everything passes: Final Question answer Yes; send for rating.
- Conversation checks pass and only basic-check items are missing (links, JSON, debug info, files, fields): Yes; reassign to the SAME annotator to fix, then send for rating.
- Debug info missing and cannot be recovered: No; reassign to the SAME annotator to redo from scratch.
- Any conversation check fails (wrong model, intent not covered, poor or copied prompts): No; reassign to ANOTHER annotator to redo from scratch.

CQ5. When should I fail a task in Conversation QC, and when should I use discretion?
Conversation QC exists to catch real problems, not to enforce one reading of a task. A fail sends the annotator back for a full redo, so it should rest on something objectively wrong that can be verified in the conversation. Where the evidence supports more than one reasonable reading, pause before failing and weigh the context.
Fail (send for re-annotation) for:
- Wrong model used (Model A: 1p-old -> flash_1p_old_test_arm).
- Seed prompt not sent exactly as Turn 1.
- An ask in the user intent never raised, or the "Stop when" condition not met.
- Follow-ups copied from plan wording or an LLM prompt, or containing made-up details.
- Debug info lost and unrecoverable.
Pause and use discretion for:
- Follow-ups close in wording where each model's reply still called for that ask.
- Models taking different directions, with each follow-up still written against its own model's replies.
- Intent wording that supports more than one reasonable reading.
These discretion cases are not automatic fails. Weigh the persona, the constraints and each model's replies, and fail only if the task still clearly falls under the fail list.

CQ6. The annotator read the intent differently from me. Should I fail the task?
Not if the wording supports the annotator's reading. An intent can be read in more than one way. Example: "narrow the logic and clarity work to the COVID-19 and faculty-acceptance sentences only, leaving the rest as is" was failed as "only edit those sentences", when the annotator's reading was to focus the work on those points and keep the introduction, conclusion and key citations intact. If the wording supports the annotator's reading, do not fail.

CQ7. Does the QC process change in Phase 6.2? Do I check or reject Model B tasks?
The QC process remains the same as in the previous phase, with these changes: do not check or reject any tasks related to Model B Conversation Generation, and focus only on Model A. Review Model A tasks, provide feedback, and approve or reject them based on the QC guidelines. The 6.2 QC specification is GAB Conversation QC v6.2 (CQ0).
