---
title: Phase 6.1 tasking flow and rating methodology
audience: all
phase: 6.1
updated: 2026-11-14
source: 'GAB Tasking Flow and Rating Methodology - v6.1.pdf, pages 1-8'
---

F1. What is the Phase 6.1 tasking and rating flow?
Phase 6.2 changes this: conversation generation is Model A only on 1p-old -> flash_1p_old_test_arm, with no Reset and no Model B (U1-U3). The Phase 6.1 flow was: Review the opening prompt and target outcome. Run Product A through the full interaction, document transcript, output and turn count, select the key turn and explain it. Rate that product immediately while it is fresh, then score its rubric separately. Reset the environment, run and rate Product B in the same manner, and record SxS preference and its written summary last. Product A is GOAT-on-Thorin DTE (Gmail Fixes) -> flash_dte_test_arm; Product B is GPT-5.6 Terra High. No screen recording is needed; Gemini debug info is mandatory.

F2. What scoring items are recorded separately?
Dimension ratings and their evidence for each product, Yes/No rubric decisions for each product, and the pair's overall SxS preference. The guide's detailed scale specifies eight L1 dimensions scored 1-5 with 2-3 sentence justifications; L2 concepts guide them. Do not collapse dimension ratings, binary rubric decisions and preference into one score.

F3. When should I score each product?
Immediately after running it. Waiting until both long interactions are over blurs the first one's details. Score each product's rubric after its dimension ratings so they remain independent, and record the SxS preference last.

F4. What are key_turn_index and key_turn_justification?
key_turn_index is the turn of highest synthesis of earlier context and tool outputs, where the primary deliverable is generated; ideally it is not Turn 1. key_turn_justification is a one-sentence explanation of why freezing just before that turn provides the richest static-context evaluation item. Record one key turn and rationale per product.

F5. What should reviewers check before rejecting a broken conversation?
Read the Conversation Context notes for generation failures, interruptions, usage-limit pauses, broken sessions or model limitations and identify which turn was affected. Debug JSON can be null when a conversation breaks or generation fails. Do not reject solely because it shows null; consider the reported model-side issues.

F6. Does the v6.1 PDF define queue limits, expiry times or feedback retention?
The supplied v6.1 tasking methodology describes running and rating the two products. It does not specify current queue limits, task expiry, pause allowances, feedback retention or platform routing stages. Ask your QM for the current platform settings rather than using previous-phase limits.

F7. How many preference choices are there when the guide says five-point?
The methodology labels preference "five-point" but explicitly lists seven choices, from Product A significantly better through No clear preference to Product B significantly better. The Stage 4 evaluation guide also explicitly calls this a seven-point scale. Use the seven listed options; ask the team if the live form differs.
