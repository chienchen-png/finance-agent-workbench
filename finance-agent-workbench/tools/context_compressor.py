"""ContextCompressor — token estimation and context compression utilities.

Phase 7.2: Provides rough token counting (4 chars ≈ 1 token for CJK/mixed text)
and message summarization for context window management.
"""

from __future__ import annotations

# Rough heuristic: 1 token ≈ 3.5 characters for mixed CJK/Latin text
# This is intentionally conservative — actual token counts vary by tokenizer.
CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    """Estimate token count for a mixed CJK/Latin string.

    Uses character-count heuristic: ~3.5 chars per token.
    For large texts, this is a reasonable approximation without a tokenizer library.
    """
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))
