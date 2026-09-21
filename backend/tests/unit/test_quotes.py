"""The quote locator is what stops the model inventing evidence.

Every test here is really one question: can a Recognition ever cite words the
user did not type? The answer has to stay "no", including when the model retypes
a curly apostrophe, flattens a line break, or is simply wrong.
"""

from __future__ import annotations

import pytest

from ros.engine.quotes import (
    locate_many,
    locate_quote,
    locate_quote_detail,
    normalize_for_match,
    verify_quote,
)

MESSAGE = "I always end up deciding on my own, even when I ask people first."

# Spelled as codepoints: a test file full of lookalike characters is exactly the
# file an editor or a formatter quietly rewrites, taking the test with it.
APOS = chr(0x2019)  # right single quotation mark
OPEN_Q = chr(0x201C)  # left double quotation mark
CLOSE_Q = chr(0x201D)  # right double quotation mark
NBSP = chr(0x00A0)
EM_DASH = chr(0x2014)
ELLIPSIS = chr(0x2026)
ZWSP = chr(0x200B)


def test_exact_match_returns_offsets_that_slice_back_to_the_quote() -> None:
    quote = "deciding on my own"
    span = locate_quote(MESSAGE, quote)
    assert span is not None
    start, end = span
    assert MESSAGE[start:end] == quote
    assert (start, end) == (MESSAGE.index(quote), MESSAGE.index(quote) + len(quote))


def test_exact_match_is_flagged_exact() -> None:
    found = locate_quote_detail(MESSAGE, "I always end up")
    assert found is not None
    assert found.exact is True
    assert found.start == 0


def test_quote_at_the_very_end() -> None:
    found = locate_quote_detail(MESSAGE, "ask people first.")
    assert found is not None
    assert found.end == len(MESSAGE)


def test_whole_message_as_the_quote() -> None:
    assert locate_quote(MESSAGE, MESSAGE) == (0, len(MESSAGE))


RETYPED = [
    ("I work late" + chr(10) + "   most nights.", "work late most nights", "newline"),
    ("I work  late   most nights.", "I work late most nights.", "double spaces"),
    ("I work" + chr(9) + "late most nights.", "I work late most nights.", "tab"),
    (f"I work{NBSP}late most nights.", "I work late most nights.", "non-breaking space"),
    (f"I don{APOS}t plan ahead.", "I don't plan ahead.", "curly to straight"),
    ("I don't plan ahead.", f"I don{APOS}t plan ahead.", "straight to curly"),
    (f"She said {OPEN_Q}no{CLOSE_Q} and I left.", 'She said "no" and I left.', "curly doubles"),
    (f"It felt slow {EM_DASH} then fine.", "It felt slow - then fine.", "em dash"),
    (f"I gave up{ELLIPSIS} eventually.", "I gave up... eventually.", "ellipsis"),
    (f"I{ZWSP}work late.", "Iwork late.", "zero-width space"),
]


@pytest.mark.parametrize(("message", "quote", "label"), RETYPED)
def test_forgiving_match_finds_retyped_quotes(message: str, quote: str, label: str) -> None:
    found = locate_quote_detail(message, quote)
    assert found is not None, label
    assert found.exact is False, label
    # The offsets point into the original message, and the slice is what must be
    # stored as `signals.quote_text` — not the model's retyped version.
    assert message[found.start : found.end] == found.text, label
    assert normalize_for_match(found.text) == normalize_for_match(quote), label


def test_forgiving_match_never_returns_a_span_that_is_not_the_quote() -> None:
    message = "I work late most nights."
    for quote in ("I work late most nights and weekends.", "I never work late", "weekends"):
        span = locate_quote(message, quote)
        if span is not None:  # pragma: no cover - the invariant, not the expectation
            start, end = span
            assert normalize_for_match(message[start:end]) == normalize_for_match(quote)


@pytest.mark.parametrize(
    ("message", "quote"),
    [
        (MESSAGE, "I never ask anyone"),
        (MESSAGE, "deciding on my own, and I like it"),
        (MESSAGE, ""),
        ("", "anything"),
        ("short", "a much longer quote than the message"),
        (MESSAGE, "   "),
    ],
)
def test_missing_quote_returns_none(message: str, quote: str) -> None:
    """None means "drop the signal and count it", never "store it anyway"."""
    assert locate_quote(message, quote) is None


def test_first_occurrence_wins() -> None:
    message = "I decide alone. Then I decide alone again."
    span = locate_quote(message, "I decide alone")
    assert span == (0, 14)


def test_surrounding_whitespace_on_the_quote_is_trimmed_from_the_span() -> None:
    found = locate_quote_detail(MESSAGE, "  deciding on my own  ")
    assert found is not None
    assert found.text == "deciding on my own"


def test_verify_quote_is_the_pre_insert_check() -> None:
    quote = "deciding on my own"
    start = MESSAGE.index(quote)
    assert verify_quote(MESSAGE, quote, start, start + len(quote)) is True
    assert verify_quote(MESSAGE, quote, start + 1, start + len(quote)) is False
    assert verify_quote(MESSAGE, quote, -1, 4) is False
    assert verify_quote(MESSAGE, quote, 5, 5) is False
    assert verify_quote(MESSAGE, quote, 0, len(MESSAGE) + 10) is False


def test_verify_quote_rejects_a_normalized_match() -> None:
    """A forgiving match is not an exact one: the stored text must be the slice."""
    message = f"I don{APOS}t plan ahead."
    found = locate_quote_detail(message, "I don't plan ahead.")
    assert found is not None
    assert verify_quote(message, "I don't plan ahead.", found.start, found.end) is False
    assert verify_quote(message, found.text, found.start, found.end) is True


def test_locate_many_splits_found_from_missing() -> None:
    found, missing = locate_many(MESSAGE, ["deciding on my own", "I never ask", "ask people first"])
    assert [f.text for f in found] == ["deciding on my own", "ask people first"]
    assert missing == ["I never ask"]


def test_normalize_is_idempotent() -> None:
    once = normalize_for_match(f"I   don{APOS}t know {EM_DASH}{NBSP}really{ELLIPSIS}")
    assert normalize_for_match(once) == once
    assert once == "I don't know - really..."
