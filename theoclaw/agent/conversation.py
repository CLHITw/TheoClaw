"""Follow-up questions: the earlier turns of a conversation, fitted into a fixed budget.

Believers and pastors think aloud: "and what about verse 9?", "make that shorter", "so how
does that fit with James?". Each new question is answered with the conversation so far, but
not with all of it: the most recent turns in full (answers cut at RECENT_CHARS), older turns
by their question only, and the whole history kept under TOTAL_CHARS. So a long conversation
costs about the same per question as a short one, and the newest context is never the part
that gets cut.
"""

from __future__ import annotations

RECENT = 3            # the last turns kept with their answers
RECENT_CHARS = 1500   # ... each answer cut to this length
OLDER_CHARS = 120     # older turns: the question only, cut to this length
TOTAL_CHARS = 7000

FOLLOW_UP = ("以下是你和使用者先前的對話。使用者這一次的問題可能接著前面說的（例如「那第 9 節呢？」「再短一點」），"
             "請按照對話的脈絡理解並回答；只回答這一次的問題，不要重複先前已經回答過的內容。")


def history_text(turns: list[tuple[str, str]], recent: int = RECENT) -> str:
    """turns: [(question, answer), ...] oldest first. Returns '' for a new conversation."""
    if not turns:
        return ""
    older, latest = turns[:-recent] if len(turns) > recent else [], turns[-recent:]
    parts = []
    if older:
        parts.append("（更早的問題）\n" + "\n".join(f"- {q[:OLDER_CHARS]}" for q, _ in older))
    for q, a in latest:
        a = a or "（沒有回答）"
        parts.append(f"使用者：{q}\n助手：{a[:RECENT_CHARS]}{'……（後略）' if len(a) > RECENT_CHARS else ''}")
    text = "\n\n".join(parts)
    while len(text) > TOTAL_CHARS and len(parts) > 1:  # drop from the oldest end, never the newest turn
        parts.pop(0)
        text = "\n\n".join(parts)
    return text[-TOTAL_CHARS:]


def follow_up_prompt(turns: list[tuple[str, str]], question: str) -> str:
    """The prompt for a question in a conversation; just the question when there is no history."""
    history = history_text(turns)
    if not history:
        return question
    return f"{FOLLOW_UP}\n\n【先前的對話】\n{history}\n\n【這一次的問題】\n{question}"
