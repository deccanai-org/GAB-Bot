---
title: GAB Evals 5 - QC Audit Spec (source of truth for final human audits)
audience: qc
phase: 5
updated: 2026-11-09
source: '"GAB Evals 5 - QC Spec Doc.pdf"'
---

## Bottom line

SP1. Key principles
- This spec is the source of truth for final human audits.
- Score each audit dimension 1 to 3, and apply the Major/Minor error classification only when that dimension scores 1.
- You audit the contributor's execution and evaluation quality. A task can pass even when the model fails, as long as the contributor pursued the assigned intent and evaluated the evidence correctly.
- Do not rerun conversations, create competing product ratings or form your own preference. You are purely auditing.
- Do not outsource audit judgement to an LLM. The task has already passed through LLM judges; this layer is the final human check.
- No need to memorise: keep the spec open and use it as you audit. Don't assume anything.
- QC must correct the criteria ratings, dimension ratings, SxS ratings and QC dimensions where they have issues; the pre-filled values are just assistance.
- Make sure justifications are not LLM-generated.

SP2. Models
Model A: Flash, Model Locust. Model B: Claude Sonnet 5.5 (thinking effort High).

SP3. Required inputs
Seeded environments, accounts, models, task criteria, the eight product dimensions and the L2 taxonomy are fixed for each task. Before starting you need: task and contributor IDs; intent and seed prompt; the criteria sheet; both numbered transcripts; both session/environment IDs; artefact names and timestamps; and the complete submission (criterion scores, 16 product ratings with justifications, both key turns, the SxS preference and summary).

## Auditor workflow

SP4. Steps
1. Check inputs and setup. If a required input that is identical for all tasks is missing, pause and contact the PM team.
2. List the asks: before reading either transcript, number every explicit ask in the seeded user intent.
3. Read A then B: read both conversations in full before looking at scoring fields. Map every intent ask to a user turn in each run (one turn can cover several asks).
4. Check the rubric criteria and all 16 product ratings on the L1 dimensions.
5. Check the supporting evidence: citations, both key turns, all dimension justifications, the SxS preference and its summary.
6. Score and record one score per audit dimension, using the scoring rubric below.

## Scores and actions

SP5. Annotator verdict (audit score)
- 1 = FAIL: only if there are conversation issues and the conversation needs to be redone or changed.
- 2 = Acceptable with feedback: the conversation is fine (no redo needed) but could have been better.
- 3 = GOOD to GO: no errors counted.

SP6. Which action do I choose? (Action dropdown, top right of the QC tab)
- Approve: the task got annotator verdict 2 or 3 and meets the quality standards.
- Reassign—Other: the task got annotator verdict 1 and the conversation quality is well below expectations, so the original annotator should not get it again. Choose this only if you have NOT corrected the task yourself and want it redone.
- If you rated annotator verdict 1 and corrected the task yourself, do not reassign; approve the task.
- During rush hours, if the screen recording has issues, redo the conversation and record it yourself, then set Annotator verdict: Fail and Action: Approve.

SP7. Product rating anchors (what annotators use for the 8 L1 dimensions, 1-5; different from your 1-3 audit scores)
5 = fully meets the dimension, no meaningful problems. 4 = meets it well, only minor issues. 3 = partly successful, a meaningful problem needing correction, re-prompting or manual work. 2 = major problems, only a small part worked or substantial recovery was needed. 1 = not satisfied, or a serious reliability/safety problem.

## Scoring rubric - Conversation setup and intent

SP8. Seed prompt fidelity (binary, Major; visible to annotator)
Check: Turn 1 in both conversations keeps the assigned seed prompt and every constraint.
1 FAIL: any alteration (wrong seed, seed split across turns, wording that adds, removes or narrows a constraint).
3 GOOD: seed retained. Whitespace, capitalisation and a meaning-neutral typo fix are fine.

SP9. Intent correctness (Major; visible)
Check: the conversation pursues the assigned deliverable.
1: pursues another deliverable, or settles for an adjacent result without meeting the intent or declaring it unmet (e.g. wrong file names never corrected).
2: a brief detour that is corrected, and the assigned intent is still pursued.
3: stays focused on the assigned intent and requests everything correctly.

SP10. Intent coverage (Major; visible)
Check: every explicit ask appears in a user turn in each conversation.
1: at least one explicit ask is never raised in one or both conversations; poor logical flow and clubbing.
2: every ask is raised, but one is raised late enough to need avoidable backtracking; any unmet outcome is acknowledged.
3: all asks raised at the relevant point. Model refusals, errors or non-completion don't affect this.

SP11. Human-written turns / no AI slop (Major; visible)
1: at least two independent AI-writing cues in one conversation, or intent pasted verbatim from the pre-seed.
2: one cue without a paste event: ask another auditor to check; do not count a Minor error.
3: prompts naturally phrased, no verbatim paste, no authorship issue.
Evidence rule: check both products. Missing records are an input issue to resolve before scoring, not automatically 1 or 2. For coverage, the contributor must raise each ask but need not make the model succeed.

## Scoring rubric - Conversation conduct and evaluation accuracy

SP12. Conversation naturalness (Major; visible)
Check: turns respond to the actual model output and progress toward a real goal.
1: checklist-like or reorderable turns; near-verbatim restatement of the intent later; reacting to something never said; a conversation designed to hit criteria instead of getting the deliverable.
2: intent stays central but phrasing is mechanical, asks are ordered unnaturally, constraints front-loaded, or an obvious model error is ignored.
3: turns build on actual output, corrections are specific, new constraints arise naturally. Shorthand, typos and varied lengths are fine.
Avoid double counting: if excess nudges are the only reason for a naturalness finding, count it under Repeated nudges only.

SP13. Debug Info JSON (binary, Major; visible - conversational dimension)
1 FAIL if any: the uploaded JSON is not the debug info JSON; it doesn't contain all turns; or a different Gemini version was used in one or more turns.
3 GOOD: a debug info JSON with Flash Model Locust in every turn.

SP14. Repeated nudges (Minor; visible)
A nudge only repeats or redirects an existing ask, adding no new information, constraint or correction. Count per intent.
1: more than three nudges on the same intent (count one Minor error for the task, even if both products exceed it).
2: no intent exceeds three, but at least one repeat was avoidable because the previous response already addressed it.
3: at most three nudges per intent, only where needed. Different intents are counted separately.

SP15. Artifact upload correctness and screen recording (Major; visible)
1: any required deliverable (conversation link, JSON PDF, model-generated artefacts) is missing for either model, or the screen recording has issues.
3: all required deliverables provided for both models.
Screen recording must have: slow, steady scrolling; all turns visible; the correct model in all turns; only the conversation page visible. If it has issues, open the chat and re-record it so all conditions are met. Report edge cases that can't be recorded at QC. Gemini conversations cannot be re-recorded at QC (the debug will be gone).

SP16. Criteria accuracy and thoroughness (Major; not visible to annotator)
1: any criterion decision plainly reversed by the evidence; two or more unsupported decisions; straight-lining despite a clear miss; justification copied across tasks; or verified time below a documented floor.
3: all reviewed decisions supported (identical pass/fail values are fine if supported).

SP17. Product dimension ratings (Major; not visible)
Validate all 16 ratings (8 dimensions x 2 models).
1: any rating off by two or more bands, or three or more ratings off by one band.
2: one or two ratings off by exactly one band.
3: all ratings match supported bands. A rating stands when no specific discrepancy can be named.

## Scoring rubric - Evidence and SxS comparison quality

SP18. Criteria turn citations (Major; not visible)
1: cited turn doesn't exist; off by more than one turn; off by one in more than 30% of citations; or doesn't support the claim (except the adjacent-turn case).
2: off by one in under 30% of citations, with the content plainly in the adjacent turn.
3: every citation points to the described content in the correct product.

SP19. Key turn citation (Major; visible)
The chosen turn should synthesise prior context and tool outputs to produce the main deliverable, or make the decisive enabling tool call.
1: the chosen turn does neither while another turn does; or Turn 1 is chosen when a later turn produces the deliverable.
2: several turns qualify but the rationale doesn't explain this choice.
3: the turn qualifies and the rationale explains the choice where several qualify.

SP20. Dimension justifications (Minor; not visible)
All 16 should give specific evidence, the relevant L2 concept, why the rating level fits, in 2-3 sentences without filler.
1: any justification lacks specific evidence, duplicates another dimension's text, contradicts its rating, describes the other product, or looks LLM-generated.
2: evidence in every one, but at least three lack an L2 concept, a rating-level explanation or writing quality.
3: all four requirements met in at least 14 of 16, with specific evidence in every one.

SP21. SxS preference consistency (Major)
1: opposite side at an absolute gap of 3 or more without an explained dominant dimension; magnitude two or more bands off; or opposing criterion pass counts without explanation.
2: magnitude one band off in the right direction (do not count a Minor error).
3: matches the anchors, or has a clearly explained permitted override; the summary explains any opposing criterion pass counts.

SP22. SxS summary (Minor)
1: no concrete comparison supported by both products; summary opposes the selected preference; or copies a dimension justification.
2: concrete evidence from both products supports the direction, but deciding dimensions, magnitude explanation or writing quality is incomplete.
3: all requirements met, and the summary explains why this strength of preference fits.
Specific evidence = a verifiable turn, quotation, named artefact, connector or tool call. An L2 concept can be named or described; its code isn't required. Count each scored dimension once.

## Update log (newest first)

SP23. 9 Nov, 8 AM IST - Screen recording while interacting with models: QC must watch the whole recording and check all turns are visible, the correct model (Flash - Locust) is used in all turns, only the conversation page is visible, and recording started from the first turn (not after the conversation).
SP24. 7 Nov, 10 PM IST - Models changed: Model A Gemini Flash (Model Locust); Model B Claude Sonnet 5.5. Screen recording added: scroll slow and steady, all turns visible, correct model, only the conversation page; re-record at QC if there are issues (not possible for Gemini).
SP25. 5 Nov, 1 PM IST - Checklist: follow "[EXT] QC Checklist/Buddy for GAB Phase 5" in order before submitting.
SP26. 2 Nov, 4 PM IST - Key turn for image/video tasks on Claude: if the main intent is image or video generation, the key turn should be 0 because the model cannot generate those files. Penalise the annotator if they didn't set 0.
SP27. 2 Nov, 12 PM IST - Conversation Context field: annotators record model issues (errors, delays, abandoning due to model issues). Do not penalise the annotator for ending a conversation when the model fails or is too slow; reflect it in the model's dimension rating instead of rejecting.
SP28. 2 Nov, 1 AM IST - LLM-written justifications: review and rewrite all justifications naturally; many were being left unchanged.
SP29. 2 Nov, 1 AM IST - Missing turns in public links: sign in to both accounts to check the conversation; never reject based only on the public link.
