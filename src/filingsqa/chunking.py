"""Split document text into overlapping chunks.

The baseline is deliberately naive: fixed-size word windows that ignore section and
table boundaries. Later experiments replace it and are compared against it.
"""

from __future__ import annotations


def fixed_word_chunks(text: str, words: int = 400, overlap: int = 50) -> list[str]:
    """Windows of `words` words; each window repeats the last `overlap` words of the previous."""
    if words <= 0 or not 0 <= overlap < words:
        raise ValueError("need words > 0 and 0 <= overlap < words")
    tokens = text.split()
    if not tokens:
        return []
    step = words - overlap
    chunks = []
    for start in range(0, len(tokens), step):
        chunks.append(" ".join(tokens[start : start + words]))
        if start + words >= len(tokens):
            break
    return chunks
