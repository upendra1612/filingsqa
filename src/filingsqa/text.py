"""Turn 10-K HTML (inline XBRL) into plain text a retriever can search."""

from __future__ import annotations

import html
import re


def html_to_text(raw: str) -> str:
    """Plain text with one line per block and table cells separated by ' | '.

    The hidden inline-XBRL header (thousands of machine tags) is removed first, so
    only what a human reader sees is kept.
    """
    raw = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)</(p|div|tr|li|h\d|table)>", "\n", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t ​]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()
