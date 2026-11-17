---
title: Phase 7.1 QC updates - thinking level checks and feedback
audience: qc
phase: 7
updated: 2026-11-17
source: 'GAB Phase 7 Conversation QC #announcements and team answers in #project-related-queries, 17 Nov 2026 (all 57 messages read 17 Nov 2026, 15:50 IST)'
---

## Thinking level of Product A

QC1. Product A was run on 3.5 Flash-Lite with Thinking level LOW. Do I reject it? Do I penalize the annotator?
It depends on when the task was submitted. Submissions before 12:00 PM IST on 17 November: reject the submission and reassign it for rework (to the same or another annotator), and do not penalize the annotator; in the feedback, say only what should be done to correct the task, without highlighting the annotator for the error. Submissions after 12:00 PM IST on 17 November: penalize the annotator, and state in the feedback that the model's thinking level must be HIGH.

QC2. Do I need to check the screen recording in QC?
Yes. Check the recordings, and rely on them to judge the model and its thinking level. When you open a conversation through the test account, the Thinking Level appears as LOW by default even if the annotator selected HIGH, so review the screen recording carefully and verify the actual model settings before rejecting a submission.

QC3. Can I check the thinking level in the debug JSON? What if the recording doesn't show the thinking level?
You can also verify it in the debug: the value shown after the Recipe ID says whether HIGH or LOW was applied. Don't rely on the debug JSON alone, because requests are routed; use it together with the screen recording.

## Feedback

QC4. Where do I write my feedback, and what goes in it?
Give your feedback in the Annotator Verdict section: describe the mistakes the annotator made. For Product A thinking-level errors, follow the wording rules in QC1 (before or after 12:00 PM IST on 17 November).

## QC documents

QC5. I can't open the QC Specification Doc ("access denied"). What do I do?
Reload the page and check again. If it still says access denied, contact the admin of this project.
