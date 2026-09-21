"""The two judge calls, and a stand-in for them that needs no network.

Two questions cannot be answered by comparing strings:

* **did KnoRI notice this?** — ``eval.judge_match``. Wording, hedging and length
  differ every run; meaning is what is being scored. A cosine would call a
  negation a match.
* **do the quotes actually support the card?** — ``eval.judge_grounding``. The
  offsets check is arithmetic and lives in ``metrics.grounding``; whether the
  words underneath really are instances of what the card claims is a reading.

Both go through the router like any other task, so they are priced, logged in
``llm_calls`` and switchable between providers from ``config/model_routing.yaml``
(the ``eval.judge_*`` row). The prompts are the versioned files under
``ros/prompts/eval/``.

Offline — which is every run in CI, and every run on a laptop with no key — the
calls are answered by :class:`OfflineJudge`, a provider that reads the same
rendered prompt and answers deterministically from word overlap and from the
arithmetic the prompt asks for. That is not a judge and this module does not
pretend it is: it makes ``./run eval`` exercise the whole pipeline end to end and
catch regressions in *everything else*. The judged numbers only mean what they
say on a live run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from evals.metrics import GoldExpectation, MatchResult, ProducedCard
from knori.scripts.seed import block, ref_chunks
from ros.llm.base import CompletionRequest, CompletionResult
from ros.llm.providers.fake import FakeProvider
from ros.llm.router import Router
from ros.llm.spec import readable_text

MATCH_TASK = "eval.judge_match"
GROUNDING_TASK = "eval.judge_grounding"
MATCH_PROMPT = "eval/judge_match"
GROUNDING_PROMPT = "eval/judge_grounding"

#: Offline only: how much of the expected observation's vocabulary a card has to
#: carry before the stand-in calls it the same observation, and before it calls it
#: related. Tuned against the corpus so that each expected observation matches its
#: own card and nothing else's. A real judge uses neither number.
SAME_COVERAGE = 0.25
RELATED_COVERAGE = 0.12

#: Words are compared on their first few characters, so "arrives" and "arrived"
#: count as the same word. Crude, but it is the difference between a stand-in that
#: measures wording and one that measures tense.
STEM_CHARS = 5

_WORDS = re.compile(r"[a-z0-9']+")
_STOPWORD_TEXT = """
    a about after again all also always am an and any are around as at back be because been
    before being between both but by came can come coming could day days did do does doing
    down each even ever every few first for from get gets getting go goes going got had has
    have having he her here hers him his how i if in into is it its just keep keeps kept
    like little look looks made make makes many may me might more most much must my never
    no not now of off often on once one only or other our out over own put puts rather re
    really said same say says see seem seems she should so some something still such take
    takes than that the their them then there these they thing things think this those
    though three time times to too two up us use used very was way we well went were what
    when where whether which while who why will with without would you your
    """
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


# ----------------------------------------------------------------- the answers


class MatchVerdict(BaseModel):
    """``eval.judge_match`` — is any produced card the expected observation?"""

    match: bool = Field(description="True only when verdict is 'same'.")
    candidate_ref: str | None = Field(
        default=None, description="Ref of the closest card, or null if none was produced."
    )
    verdict: str = Field(description="same|related|different")
    reason: str = Field(default="", description="One sentence.")


class QuoteVerdict(BaseModel):
    ref: str
    supports: bool
    reason: str = ""


class GroundingVerdict(BaseModel):
    """``eval.judge_grounding`` — do the cited quotes hold the card up?"""

    grounded: bool
    supporting_count: int = 0
    distinct_days: int = 0
    quotes: list[QuoteVerdict] = Field(default_factory=list)
    reason: str = ""


# ------------------------------------------------------------ the offline stand-in

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_QUOTED = re.compile(r'"([^"\n]*)"')
_FIELD = re.compile(r"^\s*(Title|Body|Explanation):\s*(.*)$")


def content_words(text: str) -> set[str]:
    """The words that carry the meaning, stemmed: no stopwords, no short noise."""
    return {
        word[:STEM_CHARS]
        for word in _WORDS.findall(text.lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


def coverage(expected: str, candidate: str) -> float:
    """How much of ``expected``'s vocabulary appears in ``candidate``. 0 when empty."""
    wanted = content_words(expected)
    if not wanted:
        return 0.0
    return len(wanted & content_words(candidate)) / len(wanted)


@dataclass(frozen=True, slots=True)
class Candidate:
    ref: str
    text: str


def read_candidates(prompt: str) -> list[Candidate]:
    """The ``[R1] Title`` / body blocks out of a rendered ``judge_match`` prompt."""
    return [
        Candidate(ref, chunk.strip()) for ref, chunk in ref_chunks(block(prompt, "produced"), "R")
    ]


def read_quotes(prompt: str) -> list[tuple[str, str, str]]:
    """``(ref, when, quote)`` out of a rendered ``judge_grounding`` prompt."""
    found: list[tuple[str, str, str]] = []
    for ref, chunk in ref_chunks(block(prompt, "cited_quotes"), "S"):
        quoted = _QUOTED.findall(chunk)
        when = _DATE.search(chunk)
        if quoted:
            found.append((ref, when.group(0) if when else "", quoted[-1]))
    return found


def read_card(prompt: str) -> dict[str, str]:
    """``{title, body, explanation}`` out of a rendered ``judge_grounding`` prompt."""
    fields: dict[str, str] = {}
    for line in block(prompt, "card").splitlines():
        hit = _FIELD.match(line)
        if hit is not None:
            fields[hit.group(1).lower()] = hit.group(2).strip()
    return fields


class OfflineJudge(FakeProvider):
    """Answers the two judge tasks without a model, from the rendered prompt.

    Deterministic by construction: the same prompt gives the same verdict in this
    process, the next one and on CI. Everything that is not a judge task falls
    through to the ordinary fake provider.
    """

    async def complete_structured(
        self, request: CompletionRequest, schema: type[Any]
    ) -> CompletionResult:
        if request.task == MATCH_TASK:
            payload: dict[str, Any] | None = self.match(readable_text(request))
        elif request.task == GROUNDING_TASK:
            payload = self.grounding(readable_text(request))
        else:
            payload = None
        if payload is None or not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            return await super().complete_structured(request, schema)

        parsed = schema.model_validate(payload)
        result = self._result(request, parsed.model_dump_json(indent=2), stop_reason="end_turn")
        result.parsed = parsed
        return result

    def match(self, prompt: str) -> dict[str, Any]:
        wanted = block(prompt, "expected").strip()
        candidates = read_candidates(prompt)
        if not candidates:
            return {
                "match": False,
                "candidate_ref": None,
                "verdict": "different",
                "reason": "No cards were produced for this persona.",
            }
        best = max(candidates, key=lambda c: coverage(wanted, c.text))
        score = coverage(wanted, best.text)
        verdict = (
            "same"
            if score >= SAME_COVERAGE
            else "related"
            if score >= RELATED_COVERAGE
            else "different"
        )
        return {
            "match": verdict == "same",
            "candidate_ref": best.ref,
            "verdict": verdict,
            "reason": f"Offline stand-in: the closest card carries {score:.0%} of the wording.",
        }

    def grounding(self, prompt: str) -> dict[str, Any]:
        quotes = read_quotes(prompt)
        card = read_card(prompt)
        written = " ".join(card.get(key, "") for key in ("title", "body", "explanation")).lower()
        copied = [ref for ref, _, quote in quotes if len(quote) >= 12 and quote.lower() in written]
        days = {when for _, when, _ in quotes if when}
        grounded = len(quotes) >= 2 and len(days) >= 2 and not copied
        reasons = []
        if len(quotes) < 2:
            reasons.append("fewer than two quotes")
        if len(days) < 2:
            reasons.append("the quotes are all from one day")
        if copied:
            reasons.append(f"the card copies {', '.join(copied)} word for word")
        return {
            "grounded": grounded,
            "supporting_count": len(quotes),
            "distinct_days": len(days),
            "quotes": [
                {"ref": ref, "supports": True, "reason": "Offline stand-in: not read."}
                for ref, _, _ in quotes
            ],
            "reason": (
                "Offline stand-in: two quotes on two days, none copied."
                if grounded
                else f"Offline stand-in: {', and '.join(reasons)}."
            ),
        }


# --------------------------------------------------------------------- the judge


class Judge:
    """The two judge calls, through the router, with the ledger written as usual."""

    def __init__(
        self,
        router: Router,
        *,
        session: AsyncSession | None = None,
        user_id: Any = None,
    ) -> None:
        self.router = router
        self.session = session
        self.user_id = user_id
        self.calls = 0

    async def match(self, gold: GoldExpectation, cards: Sequence[ProducedCard]) -> MatchResult:
        """Did any of these cards make the expected observation?"""
        refs = {f"R{index + 1}": card for index, card in enumerate(cards)}
        answer = await self._run(
            MATCH_TASK,
            MATCH_PROMPT,
            {
                "gold": {"statement": gold.gist, "note": gold.note},
                "candidates": [
                    {"ref": ref, "title": card.title, "body": card.body}
                    for ref, card in refs.items()
                ],
            },
            MatchVerdict,
        )
        chosen = refs.get(answer.candidate_ref or "")
        return MatchResult(
            gold_id=gold.id,
            matched=answer.match and answer.verdict == "same" and chosen is not None,
            card_id=chosen.id if chosen is not None else None,
            verdict=answer.verdict,
            reason=answer.reason,
        )

    async def grounding(self, card: ProducedCard) -> GroundingVerdict:
        """Do the quotes this card cites actually hold it up?"""
        return await self._run(
            GROUNDING_TASK,
            GROUNDING_PROMPT,
            {
                "card_title": card.title,
                "card_body": card.body,
                "card_explanation": card.explanation,
                "quotes": [
                    {"ref": quote.ref, "when": quote.observed_on, "quote": quote.quote_text}
                    for quote in card.quotes
                ],
            },
            GroundingVerdict,
        )

    async def _run[T: BaseModel](
        self, task: str, prompt: str, variables: Mapping[str, Any], schema: type[T]
    ) -> T:
        self.calls += 1
        result = await self.router.run(
            task,
            prompt=prompt,
            vars=dict(variables),
            schema=schema,
            user_id=self.user_id,
            session=self.session,
        )
        parsed = result.parsed
        if not isinstance(parsed, schema):
            raise RuntimeError(
                f"{task} returned {type(parsed).__name__}, expected {schema.__name__}"
            )
        return parsed


__all__ = [
    "GROUNDING_TASK",
    "MATCH_TASK",
    "RELATED_COVERAGE",
    "SAME_COVERAGE",
    "Candidate",
    "GroundingVerdict",
    "Judge",
    "MatchVerdict",
    "OfflineJudge",
    "QuoteVerdict",
    "content_words",
    "coverage",
    "read_candidates",
    "read_card",
    "read_quotes",
]
