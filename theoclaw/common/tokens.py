"""Exact token counts from the Messages API count_tokens endpoint (free of charge,
rate limited). Token counts are model-specific: newer models use a tokenizer that
produces more tokens for the same text, so always count with the model you will use.
"""

from __future__ import annotations

CHUNK_CHARS = 150_000  # well under every model's context window, even for Chinese text


def _chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            end = cut + 1 if cut > start else end
        out.append(text[start:end])
        start = end
    return out


class TokenCounter:
    """Counts the tokens of a piece of text (without the few tokens of message framing)."""

    def __init__(self, client, model: str):
        self.client, self.model = client, model
        self._overhead: int | None = None

    def _raw(self, text: str) -> int:
        resp = self.client.messages.count_tokens(model=self.model, messages=[{"role": "user", "content": text}])
        return int(resp.input_tokens)

    @property
    def overhead(self) -> int:
        if self._overhead is None:
            self._overhead = self._raw("x") - 1  # framing tokens around a one-token message
        return self._overhead

    def count(self, text: str) -> int:
        if not text.strip():
            return 0
        return sum(max(0, self._raw(chunk) - self.overhead) for chunk in _chunks(text))
