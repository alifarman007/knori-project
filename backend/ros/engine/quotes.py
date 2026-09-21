"""Finding the user's words inside the user's message.

This is the smallest and most important function in the engine. Every signal
carries a verbatim quote with character offsets, and nothing is stored until
``message.content[start:end] == quote_text`` holds (CLAUDE.md engine rule 2).
If the model returns words that are not in the message, the quote cannot be
located and the signal is dropped and counted. That is what makes it impossible
for a Recognition to cite evidence that was never typed.

Models retype text slightly: a straight apostrophe for a curly one, a single
space for a line break, a decomposed accent. So an exact search is tried first,
then a forgiving one that ignores exactly those differences — and the forgiving
match still returns offsets into the *original* text, verified by re-normalising
the span it found. A span whose slice does not normalise to the quote is never
returned.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Characters a model routinely swaps. NFKC handles the rest (non-breaking and
# thin spaces, full-width forms, ligatures).
_FOLD_GROUPS: dict[str, tuple[int, ...]] = {
    # Built from codepoints rather than literals: a file full of lookalike
    # characters is exactly the file a formatter or an editor quietly rewrites.
    "'": (0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x00B4, 0x0060),
    '"': (0x201C, 0x201D, 0x201E, 0x201F, 0x2033, 0x00AB, 0x00BB),
    "-": (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212),
    "...": (0x2026,),
    # Zero-width and byte-order marks carry no text; drop them entirely.
    "": (0x200B, 0x200C, 0x200D, 0xFEFF),
}

_FOLD: dict[str, str] = {
    chr(code): target for target, codes in _FOLD_GROUPS.items() for code in codes
}


@dataclass(frozen=True, slots=True)
class QuoteMatch:
    """Where a quote was found, and the text that is actually there.

    ``text`` is the slice of the original message, which is what must be stored
    as ``signals.quote_text``: storing the model's retyped version would break
    the ``content[start:end] == quote_text`` check on the next read.
    """

    start: int
    end: int
    text: str
    exact: bool


def _fold_char(ch: str) -> str:
    folded = _FOLD.get(ch)
    return unicodedata.normalize("NFKC", ch) if folded is None else folded


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Normalise ``text`` and remember, per output character, where it came from."""
    out: list[str] = []
    origin: list[int] = []
    for index, ch in enumerate(text):
        folded = _fold_char(ch)
        if folded == "":
            continue
        if not folded.strip():
            # Any run of whitespace, of any width, counts as one plain space.
            if out and out[-1] != " ":
                out.append(" ")
                origin.append(index)
            continue
        for out_ch in folded:
            out.append(out_ch)
            origin.append(index)
    return "".join(out), origin


def normalize_for_match(text: str) -> str:
    """The comparison form: folded punctuation, collapsed whitespace, NFKC."""
    return _normalized_with_map(text)[0].strip()


def locate_quote(message_text: str, quote: str) -> tuple[int, int] | None:
    """Character offsets of ``quote`` inside ``message_text``, or None.

    ``None`` means "drop this signal and count it" — never "store it anyway".
    """
    found = locate_quote_detail(message_text, quote)
    return None if found is None else (found.start, found.end)


def locate_quote_detail(message_text: str, quote: str) -> QuoteMatch | None:
    """As :func:`locate_quote`, plus the original slice and whether it was exact."""
    if not message_text or not quote:
        return None

    exact_at = message_text.find(quote)
    if exact_at != -1:
        return QuoteMatch(exact_at, exact_at + len(quote), quote, exact=True)

    norm_text, origin = _normalized_with_map(message_text)
    norm_quote = normalize_for_match(quote)
    if not norm_quote:
        return None

    at = norm_text.find(norm_quote)
    while at != -1:
        start = origin[at]
        end = origin[at + len(norm_quote) - 1] + 1
        span = message_text[start:end]
        # The invariant: a span is only returned when it really is the quote.
        if normalize_for_match(span) == norm_quote:
            return QuoteMatch(start, end, span, exact=False)
        at = norm_text.find(norm_quote, at + 1)
    return None


def verify_quote(message_text: str, quote_text: str, start: int, end: int) -> bool:
    """The check run immediately before insert, and again on every read back."""
    if start < 0 or end <= start or end > len(message_text):
        return False
    return message_text[start:end] == quote_text


def locate_many(message_text: str, quotes: list[str]) -> tuple[list[QuoteMatch], list[str]]:
    """Locate several quotes from one message; returns (found, not_found)."""
    found: list[QuoteMatch] = []
    missing: list[str] = []
    for quote in quotes:
        match = locate_quote_detail(message_text, quote)
        if match is None:
            missing.append(quote)
        else:
            found.append(match)
    return found, missing
