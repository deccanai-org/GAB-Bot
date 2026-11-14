---
title: QC Checklist / Buddy for GAB Phase 5 (chronological QC flow)
audience: qc
phase: 5
updated: 2026-11-09
source: '"[EXT] QC Checklist_Buddy for GAB Phase 5.pdf"'
---

CL0. What changed in the 9 Nov 2026 (V5) version of the QC checklist?
- The Gemini model changed to Flash, Model Locust.
- Screen recording must cover the whole conversation, not just the end, because it is used to measure response latency.

CL1. Screen recording verification
- The recording covers all conversation turns, with slow, steady, readable scrolling.
- The correct model is used across all turns.
- Only the conversation page is visible.
- If any of these are not met, re-record at the QC stage. Report cases where re-recording is not possible. Do NOT re-record Gemini conversations: the debug information will be lost.

CL2. Login credentials verification
Check the annotator logged in with the Task Email and Task Password given on the Instructions page.

CL3. Confirm the model
- Gemini: Flash, then Model Locust.
- Claude: Claude Sonnet 5.5, thinking mode "high".
- Tip: track the model throughout the conversation; models have reverted to another model without the annotator choosing it.

CL4. How annotators should work with the user intent (what to expect when reviewing)
- The seed prompt is sent exactly as written. That is Turn 1.
- The unedited user goal is background only and must never be pasted to the model.
- Each turn line is an aim, not a script: the annotator writes their own message in the given voice, in their own words.
- Each turn stays inside its word range ("under 10 words" means under 10 words).
- If a turn lists (a) and (b), the message must cover both. Re-read the line before sending.
- The annotator reacts to what the model actually said: skips a turn the model already covered, doesn't add turns to fill time.
- Expected outcome lines are never said to the model.

CL5. Conversation generation benchmarks to evaluate (see "How to Converse with the Model" in the GAB Instructions - Production - v5)
a. The seed prompt is reproduced entirely, unchanged, at the start of the conversation.
b. The "Turn guidance" instructions are NOT pasted word for word.
c. Intent coverage MUST be assessed: all the user's asks are covered, in the allocated persona.
d. Conversations should NOT read alike from one task to the next: follow-ups vary in length and shape.
e. A conversation is complete when all objectives in the "Unedited user goal" AND "Stop When" are achieved.
f. The conversation reads naturally: prompts naturally phrased, no verbatim paste from the user intent.
g. Track nudges per intent: at most three nudges per intent, used only where the model still needs to address the ask. Different intents are counted separately.
h. Coverage: the annotator must raise each ask but need not make the model succeed. Reflect the model's failure in the relevant criterion and dimension rating; do not reject the task for that. A task can pass even when the model fails, as long as the contributor pursued the assigned intent and evaluated the evidence correctly.
i. Rule of thumb: no apparent LLM usage in generating the conversation. It's more than em dashes: ask whether a person would write the prompt that way. Minor grammar or spelling errors are fine.

CL6. Pro tip: intent coverage first
Intent coverage is one of the main QC priorities. A task may be returned entirely for rework if the conversation fails to address all requirements in the designated persona. First check the annotator generated the conversation in line with the instructions (short, one-liner, brief, elaborate) and persona. Reviewing individual criteria and dimensions is pointless if the overall intent was not covered.

CL7. Uploads and outputs for Model A and B
a. Verify every conversation link, artefact, key turn citation, JSON and debug file MANUALLY. Don't review only through the public link: sign in to the respective accounts and open the links in both Claude and Gemini. Public links sometimes don't show all turns, so never reject without checking the complete conversation while signed in.
b. Only final artefacts are uploaded, not ones sent back to the model for rework. Original formats are kept; only Calendar invites and Mail drafts are uploaded as PDFs.
c. Manually verify the invites are in Calendar and the emails are in Gmail Drafts, after logging into the designated account. Do not copy content into a new Google Doc to make PDFs.
d. Check the Chat JSON and Debug files carefully: turns must match and debug information must be present. Every turn needs its own entry, none missing and no extra.
e. Read the JSON carefully: the artefact field cannot be "NA" for a turn that generated an artefact. Flag and report such discrepancies at both the annotation and QC layers.
f. The Key Turn citation must match its justification, and the justification must be valuable: explain the choice where several turns qualify, not state the obvious.

CL8. Criteria and dimension ratings (both models)
a. Turns cited for each criterion/dimension must align. These are auto-generated and need a sharp human eye.
b. Dimension justifications must match the turns cited (e.g. if turn 10 is cited but the justification only talks about turns 4 or 5, that's wrong).
c. All justifications must be reviewed and rewritten in a natural, human-written way, not LLM-sounding and not copied from the auto-generated assistance.

CL9. Scoring rubric
The audit scores are auto-generated too and must be verified carefully. For example, if the annotator did poorly on "Artifact Upload Correctness", the rating should not be 3. Refer to the scoring rubric sections of the QC spec: Conversation setup and intent; Conversation conduct and evaluation accuracy; Evidence and SxS comparison quality.

CL10. SxS preference
A distinct 2-3 sentence comparison that names the deciding dimensions, gives concrete evidence from each product and explains the preference strength. It MUST be consistent with how each model scored on the criteria and dimensions. Flag immediately if, for example, the annotator prefers Model A while Model B clearly performed better.

CL11. Feedback guidelines
Write one line per finding: what is wrong, where it appears, and what the contributor should fix. For failures, lead with the Major dimension scored 1 or the three Minor dimensions scored 1. Label score-2 findings clearly as feedback, not counted errors.
