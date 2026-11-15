"""Conversation normalization and tool-free provider request policy."""

from __future__ import annotations

FORBIDDEN_REQUEST_KEYS = ("tools", "tool_choice", "functions", "function_call", "mcp_servers")


class ToolUseForbidden(RuntimeError):
    """A request to an answering model tried to give it tools."""


def assert_no_tools(request: dict) -> dict:
    """Refuse to send a model request that carries tools (enforced in code, not only in the prompt)."""
    found = [k for k in FORBIDDEN_REQUEST_KEYS if k in request]
    if found:
        raise ToolUseForbidden(f"answering models may not be given tools: {found}")
    return request


def normalize_history(
    history: list[dict] | None, limit: int, *, keep_last_user=False
) -> list[dict]:
    """Make earlier thread messages into a valid conversation: only the last `limit` messages,
    starting with a user message, with consecutive messages from the same side merged."""
    if limit <= 0:
        return []
    merged: list[dict] = []
    for msg in (history or [])[-limit:]:
        text = (msg.get("content") or "").strip()
        role = msg.get("role")
        if not text or role not in ("user", "assistant"):
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] += "\n\n" + text
        else:
            merged.append({"role": role, "content": text})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    # The new question is appended as a user message, so history must end with the assistant.
    if merged and merged[-1]["role"] == "user" and not keep_last_user:
        merged.pop()
    return merged
