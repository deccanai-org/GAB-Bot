---
title: ARCHIVED - GAB Single Model Instructions (single-model workflow)
audience: all
phase: unknown
status: archived
note: 'Not loaded by the bot. This workflow uses ONE model ("Gemini 3.6 Flash"), zipped artefacts and an LLM-made JSON, which conflicts with Phase 5 (Flash -> Model Locust + Claude Sonnet 5.5). Its scoring sections are kept in knowledge/current/rating-reference.md. Move this back to current/ only if the single-model workflow is confirmed active.'
source: '"GAB Single Model Instructions.pdf"'
---

- Product A: Gemini 3.6 Flash (single model only).
- Workflow: set up (intent, opening prompt, persona, test account) -> drive the conversation on Model A -> capture link, artefacts, total turns, key turn -> convert the conversation to JSON PDF -> rate A's binary criteria with criterion turns -> rate A's 8 dimensions (1-5) with justifications and turns.
- Artefacts zipped before upload (later note in the same doc: no zip needed any more, upload files individually).
- Conversation JSON: in the same Gemini account, start a new chat, give it the conversation PDF and ask it to convert to JSON (or use the Gemini conversation exporter script, conversation.json only, no debug info).
- Share link: chat dropdown -> "Share via Drive" -> Proceed -> General Access "Anyone with the link" -> Copy link.
- Strict fraud guidelines: window switching only to the designated tasking account; no browser switching.
