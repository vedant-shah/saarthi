"""Em-dash removal for user-facing text.

No user-facing screen may show an em dash. `replace_em_dashes` rewrites each
one from its context: numeric ranges get a plain hyphen, a dash introducing a
capitalised clause becomes a colon, everything else becomes a comma. Intended
for any text we author or relay (advisor chat output, onboarding copy checks,
memory summaries).
"""
from __future__ import annotations

import re

# One or more em dashes plus the spaces/tabs hugging them; replacements
# provide their own spacing. Newlines are deliberately not consumed.
_EM_DASH_RUN = re.compile(r"[ \t]*—+[ \t]*")

_ALREADY_PUNCTUATED = set(",;:([{")


def _replacement(prev: str, nxt: str) -> str:
    """Pick the substitute from the characters flanking the dash run."""
    if prev.isdigit() and nxt.isdigit():
        return "-"  # a range: 2019-2024
    if not nxt or nxt == "\n":
        return ""  # trailing dash adds nothing
    if not prev or prev == "\n":
        return "- "  # line-leading dash reads as a list/dialogue marker
    if prev in _ALREADY_PUNCTUATED:
        return " "  # the clause break already exists
    if nxt.isupper():
        return ": "  # introduces a capitalised clause
    return ", "


def replace_em_dashes(text: str) -> str:
    """Return `text` with every em dash replaced per `_replacement`."""
    parts: list[str] = []
    pos = 0
    for match in _EM_DASH_RUN.finditer(text):
        left = text[pos : match.start()]
        parts.append(left)
        seen = "".join(parts)
        prev = seen[-1:] if seen else ""
        nxt = text[match.end() : match.end() + 1]
        parts.append(_replacement(prev, nxt))
        pos = match.end()
    parts.append(text[pos:])
    return "".join(parts)


# A blank line (two newlines, optionally with whitespace between) is how the
# advisor marks "send this as a separate text". Greedy whitespace collapses
# runs of blank lines into a single split.
_BLANK_LINE = re.compile(r"\n\s*\n")


def to_bubbles(text: str) -> list[str]:
    """Split a reply into chat bubbles on blank lines, em-dash-sanitize each,
    and drop empty ones. Text with no blank line yields a single bubble; empty
    or whitespace-only text yields no bubbles. This is the one path every
    advisor reply takes before reaching the user, so no bubble can contain an
    em dash."""
    bubbles: list[str] = []
    for chunk in _BLANK_LINE.split(text):
        cleaned = replace_em_dashes(chunk).strip()
        if cleaned:
            bubbles.append(cleaned)
    return bubbles
