---
title: Phase 5 task flow - what happens to a task from annotation to the end
audience: all
phase: 5
updated: 2026-11-11
source: 'Cosmo workflow configuration for "GAB Eval V5" (stage settings and flow diagram)'
---

## The stages, in order

F1. What are the stages a Phase 5 task goes through?
1. Default Annotation (annotators, team "GAB Eval V5 - Ann"): the annotator generates both conversations and fills in the task. Actions: Submit or Skip.
2. Agent (automated AI check, no human): an AI reviewer checks the submitted task (conversations, debug JSON, key turns, turn counts, artefacts, links) and pre-fills ratings, justifications, fail reasons and checks. Whatever it decides (approve or reject), the task always goes on to human Quality Check. These are the "auto-rated" ratings and justifications that QC reviewers must review and rewrite.
3. Quality Check (QC reviewers, team "GAB Eval V5 - QC"): a human reviews the task using the QC spec and checklist. Actions: Approve (task moves to Holding Layer) or send it back to Default Annotation for rework.
4. Holding Layer (QC team): a further review layer after QC. Approve moves the task to QA; it can also be sent back to Quality Check.
5. QA (team "GAB Eval V5 - QA"): quality assurance review. Approve or Reject; both move the task to Super QA.
6. Super QA (QA team): final quality decision. Approve moves the task to Holding Layer 2; Reject sends it to Re-Annotation.
7. Re-Annotation (team "GAB Eval V5 - Re Annotation"): tasks rejected at Super QA are fixed here. Actions: Submit (moves to Holding Layer 2) or Skip.
8. Holding Layer 2 (Re-Annotation team): last check. Approve ends the task (done).

F2. Short version of the flow
Default Annotation -> Agent (AI check) -> Quality Check -> Holding Layer -> QA -> Super QA -> Holding Layer 2 -> End.
If Super QA rejects: Super QA -> Re-Annotation -> Holding Layer 2 -> End.
Send-backs: Quality Check can send a task back to annotation; Holding Layer can send it back to Quality Check.

## For annotators (Default Annotation stage)
<!-- audience: annotator -->

F3. What happens after I submit a task?
It goes to the automated Agent check, then to a human QC reviewer. The QC reviewer either approves it (it moves on through further review layers) or sends it back to you for rework.

F4. What does "Skip" do?
Skipping returns the task to the Default Annotation queue so it can be picked up again; it does not move forward. (Don't skip just because Drive/Gmail files are mismatched or missing - see the FAQ: share your test account and persona with the team instead.)

F5. What does it mean if my task was sent back / reassigned?
The QC reviewer found something that needs fixing and returned the task to the annotation stage for rework. Check the QC feedback on the task, fix the issues, and submit again. After you resubmit, it goes through the Agent check and Quality Check again, possibly with a different QC reviewer.

F6. Can I see QC feedback on my tasks?
Yes. In the annotation stage you can see the feedback from the Quality Check stage for 10 days.

F7. How many tasks can I hold or pick up?
You can work on 1 task at a time, and pick up at most 2 tasks per hour.

F8. How long do I have to finish a task?
A task expires 5 hours after you pick it up. The time limit is shown on screen.

F9. Can I pause a task?
Yes. You can have at most 1 paused task, and a pause can last at most 1 hour.

## For QC reviewers (Quality Check stage)
<!-- audience: qc -->

F10. What actions do I have in Quality Check?
Approve, or send the task back to annotation for rework (Reassign). Approved tasks move to the Holding Layer.
Note: the QC spec describes the send-back option as "Reassign—Other" (use it only when you gave annotator verdict 1, did not correct the task yourself, and want it redone). The platform's Quality Check stage is configured with "Reassign—Same" (back to the same annotator). If the option you need isn't in the action dropdown, check with your QM.
If you rated annotator verdict 1 but corrected the task yourself, do not reassign; approve it.

F11. How many times can a task be sent back?
From Quality Check, a task can be sent back to the same annotator up to 6 times (and to a different annotator at most once). From the Holding Layer, a task can be sent back to Quality Check (to the same reviewer once).

F12. When an annotator resubmits a reworked task, does it come back to me?
Not necessarily. Reworked tasks are not routed back to the same reviewer; any QC reviewer may pick it up.

F13. How many QC tasks can I hold or pick up?
Up to 3 tasks at a time and up to 20 per hour. Each task expires 5 hours after you pick it up. You can have 1 paused task, for at most 2 hours.

F14. Where do the pre-filled (auto-rated) ratings and justifications come from?
From the automated Agent stage (an AI reviewer). They are only assistance: correct the criteria ratings, dimension ratings, SxS rating and QC dimensions where needed, and rewrite every justification in your own natural words.

F15. Can I see feedback on my QC work?
Yes, QC reviewers can see the feedback from the Holding Layer for 30 days.

## Re-Annotation stage

F16. What is Re-Annotation?
When Super QA rejects a task, it goes to the Re-Annotation team, who fix it and submit it (Submit) or skip it back to the Re-Annotation queue (Skip). Submitted re-annotations go to Holding Layer 2 for a final approval. Re-annotators can hold up to 50 tasks, pick up to 20 per hour, and each task expires after 5 hours; pausing is not available in this stage.
