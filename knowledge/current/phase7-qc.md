---
title: Phase 7.1 QC updates - thinking level checks and feedback
audience: qc
phase: 7
updated: 2026-11-18
source: 'GAB Phase 7 Conversation QC #announcements and team answers in #project-related-queries, 17 Nov 2026 (all 57 messages read 17 Nov 2026, 15:50 IST; team answers up to 22:40 IST; all messages re-read 17 Nov 2026, 22:50 IST; all messages from 22:40 IST on 17 Nov to 04:05 IST on 18 Nov read 18 Nov 2026, 04:40 IST)'
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

## Reassigning and rejecting

QC6. The annotator did everything right but used the Task tab, not the Chat tab, for Model B. What do I do?
Give a rating of 2 and reassign the task. If the conversations themselves are correct, select "Conversations are sufficient". A QC task you already submitted before the Chat-tab-only rule can't be returned to your queue; apply the rule from now on.

QC7. Do I reassign to the same annotator or another one? Does the environment need a reset?
If the only issue is the thinking level, reassign to the same annotator. Reassigning to the same annotator needs an environment reset. If the wrong model was selected and the conversation is incomplete, you can reassign to another annotator.

QC8. The screen recording is only a couple of minutes, for example only the output generation time. What do I do?
Penalize it and reassign the task to another annotator. The whole interaction must be recorded, from the model selection step to the final response (S5).

QC9. Required files are missing or empty (debug, recording, share link), and the form won't let me submit the rejection. What do I do?
Upload dummy files to proceed with the submission, then reject the task. In the feedback, state clearly that the files uploaded by the annotator were empty or missing, so dummy files were added to complete the submission, and ask them to upload the correct files and complete the task properly during rework.

QC10. The debug JSON is missing a conversation turn, but the screen recording is complete and the model didn't stop. Do I send it back?
Yes: assign it back for rework to the same annotator.

QC11. Only one artifact file is missing (for example, one Model B file) and there are no other issues. Do I reject?
No: if nothing else is wrong, add the missing file and mark the task acceptable. If required files such as the debug, the recording or the share link are missing or empty, follow QC9.

## Checking the conversation

QC12. The debug info shows an email was sent successfully and the conversation says "Message sent". Do I also need to check the Gmail Sent folder?
Yes, check in Gmail as well that the email was sent.

QC13. The last message of the conversation, a closing message such as "All done, thanks!", isn't in the screen recording. Is that a problem?
No, that's fine as long as all the required turns are included in the recording.

QC14. The first prompt of the conversation is a memory check such as "Do you remember our conversation?". Do I ignore it?
Yes, ignore it and proceed with the review. Asking the model about earlier work before the seed prompt is optional for annotators (S20).

## QC tasks

QC15. "Start New Task" says "No pending tasks are available for you" in QC. Are there QC tasks left? Are there ML or coding QC tasks?
Reload the page and check again; the team adds QC tasks as annotation submissions come in. On 18 Nov 2026 (about 1 AM IST) the team said only generalist tasks were left for QC, with no ML or coding QC tasks at that time. To ask for a higher QC task limit, contact the admin of this project.
