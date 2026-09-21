"""Code validation of what the model proposed, and of what gets written on a card.

Two halves of the same idea: the model chooses the words, never the facts.

* ``validate_proposals`` decides which proposals may become rows at all. One bad
  item is rejected on its own — a batch is never thrown away;
* ``build_provenance`` checks the receipt: at least two supporting quotes, in
  weight order, and card text that paraphrases instead of repeating them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ros.engine.provenance import MessageMeta, build_provenance
from ros.engine.types import EvidenceIn, InterpretationIn, SignalIn, UserPolicy
from ros.engine.validate import (
    ValidationPolicy,
    is_third_person,
    validate_declined,
    validate_proposals,
)
from ros.schemas.llm_io import (
    Declined,
    InterpretationBatch,
    Proposal,
    ProposedEvidence,
    RecognitionDraft,
)

DAY1 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
STATEMENT = "The user makes the final call alone after asking other people first."


def sig(ref: str, *, subject: str = "self", sensitive: str | None = None, **kw) -> SignalIn:
    return SignalIn(
        id=f"sig-{ref}",
        subject=subject,
        topic="work.decisions",
        strength=1.0,
        observed_at=kw.pop("observed_at", DAY1),
        message_id=kw.pop("message_id", f"msg-{ref}"),
        quote_text=kw.pop("quote_text", f"quote {ref}"),
        sensitive_category=sensitive,
        **kw,
    )


SIGNALS = {"S1": sig("1"), "S2": sig("2", observed_at=DAY2, message_id="msg-2")}
POLICY = ValidationPolicy(user=UserPolicy())


def evidence(*refs: str, role: str = "supports", weight: float = 1.0) -> list[ProposedEvidence]:
    return [ProposedEvidence(signal_ref=ref, role=role, weight=weight, note="why") for ref in refs]


def proposal(**kw) -> Proposal:
    base: dict = {
        "action": "create",
        "kind": "pattern",
        "topic": "work.decisions",
        "statement": STATEMENT,
        "rationale": "Two separate messages, two days apart.",
        "model_confidence": 0.8,
        "evidence": evidence("S1", "S2"),
    }
    base.update(kw)
    return Proposal(**base)


def run(*proposals: Proposal, policy: ValidationPolicy = POLICY, targets=None):
    batch = InterpretationBatch(proposals=list(proposals))
    return validate_proposals(batch, SIGNALS, targets or {}, policy)


# ------------------------------------------------------------- the happy path


def test_a_good_proposal_is_accepted_with_its_refs_resolved() -> None:
    accepted, rejections = run(proposal())
    assert rejections == []
    assert len(accepted) == 1
    assert [e.signal_id for e in accepted[0].supports] == ["sig-1", "sig-2"]
    assert accepted[0].target_id is None


def test_one_bad_item_never_costs_the_batch() -> None:
    accepted, rejections = run(proposal(), proposal(kind="mood"))
    assert [a.index for a in accepted] == [0]
    assert [(r.rule, r.reason) for r in rejections] == [("V13", "unknown_kind")]


# ----------------------------------------------------- V1: what may support


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"subject": "other"}, "subject=other"),
        ({"subject": "hypothetical"}, "subject=hypothetical"),
        ({"subject": "unclear"}, "subject=unclear"),
        ({"sensitive": "mental_health"}, "sensitive"),
    ],
)
def test_v1_only_self_and_non_sensitive_signals_may_support(kwargs: dict, detail: str) -> None:
    signals = {"S1": sig("1"), "S2": sig("2", **kwargs)}
    batch = InterpretationBatch(proposals=[proposal()])
    accepted, rejections = validate_proposals(batch, signals, {}, POLICY)
    assert [e.signal_ref for e in accepted[0].supports] == ["S1"]
    dropped = accepted[0].dropped[0]
    assert (dropped.rule, dropped.reason, dropped.scope) == (
        "V1",
        "supports_not_eligible",
        "evidence",
    )
    assert dropped.detail == detail
    assert rejections == [dropped]


def test_v1_does_not_restrict_context_or_contradicting_evidence() -> None:
    """The user's words about other people stay their words — just not support."""
    signals = {"S1": sig("1"), "S2": sig("2"), "S3": sig("3", subject="other")}
    accepted, _ = validate_proposals(
        InterpretationBatch(
            proposals=[proposal(evidence=evidence("S1", "S2") + evidence("S3", role="context"))]
        ),
        signals,
        {},
        POLICY,
    )
    assert [(e.signal_ref, e.role) for e in accepted[0].evidence] == [
        ("S1", "supports"),
        ("S2", "supports"),
        ("S3", "context"),
    ]


def test_v5_a_create_with_nothing_left_to_support_it_is_rejected() -> None:
    signals = {"S1": sig("1", subject="other")}
    accepted, rejections = validate_proposals(
        InterpretationBatch(proposals=[proposal(evidence=evidence("S1"))]), signals, {}, POLICY
    )
    assert accepted == []
    assert [r.rule for r in rejections] == ["V5", "V1"]


# --------------------------------------------------------- evidence hygiene


def test_v2_a_ref_that_was_not_in_the_input_is_dropped() -> None:
    accepted, rejections = run(proposal(evidence=evidence("S1", "S2", "S99")))
    assert [e.signal_ref for e in accepted[0].evidence] == ["S1", "S2"]
    assert rejections[0].rule == "V2"
    assert rejections[0].ref == "S99"


def test_v3_the_same_signal_is_only_counted_once() -> None:
    accepted, rejections = run(proposal(evidence=evidence("S1", "S2", "S1")))
    assert [e.signal_ref for e in accepted[0].evidence] == ["S1", "S2"]
    assert rejections[0].rule == "V3"


def test_v4_an_invented_role_is_dropped() -> None:
    signals = {**SIGNALS, "S3": sig("3")}
    accepted, rejections = validate_proposals(
        InterpretationBatch(
            proposals=[proposal(evidence=evidence("S1", "S2") + evidence("S3", role="proves"))]
        ),
        signals,
        {},
        POLICY,
    )
    assert rejections[0].rule == "V4"
    assert len(accepted[0].evidence) == 2


def test_weights_and_model_confidence_are_clamped_not_rejected() -> None:
    """Wire schemas carry no numeric constraints, so code clamps per item."""
    accepted, _ = run(proposal(evidence=evidence("S1", "S2", weight=7.5), model_confidence=3.2))
    assert {e.weight for e in accepted[0].evidence} == {1.0}
    assert accepted[0].model_confidence == 1.0

    accepted, _ = run(proposal(evidence=evidence("S1", "S2", weight=-4.0), model_confidence=-1.0))
    assert {e.weight for e in accepted[0].evidence} == {0.0}
    assert accepted[0].model_confidence == 0.0


# ------------------------------------------------------------ the statement


@pytest.mark.parametrize(
    "statement",
    [
        "You tend to decide alone.",
        "I notice the user decides alone.",
        "We think the user decides alone.",
        "The user decides alone, and your instinct is usually right.",
    ],
)
def test_v11_a_statement_is_a_claim_not_a_card_sentence(statement: str) -> None:
    accepted, rejections = run(proposal(statement=statement))
    assert accepted == []
    assert (rejections[0].rule, rejections[0].reason) == ("V11", "not_third_person")


@pytest.mark.parametrize(
    "statement",
    [
        STATEMENT,
        "The user prefers written updates to meetings.",
        "Alif plans the week on Sunday evenings.",
    ],
)
def test_third_person_statements_pass(statement: str) -> None:
    from ros.engine.types import load_thresholds

    assert is_third_person(statement, load_thresholds().validation) is True


@pytest.mark.parametrize("statement", ["", "short", "x" * 401])
def test_v12_an_empty_or_runaway_statement_is_rejected(statement: str) -> None:
    accepted, rejections = run(proposal(statement=statement))
    assert accepted == []
    assert rejections[0].rule == "V12"


def test_v14_a_topic_outside_the_taxonomy_is_rejected() -> None:
    policy = ValidationPolicy(allowed_topics=frozenset({"work.decisions"}))
    accepted, rejections = run(proposal(topic="astrology.signs"), policy=policy)
    assert accepted == []
    assert rejections[0].rule == "V14"


def test_v15_an_invented_sensitive_category_is_rejected() -> None:
    accepted, rejections = run(proposal(sensitive_category="vibes"))
    assert accepted == []
    assert rejections[0].rule == "V15"


def test_v0_an_invented_action_is_rejected() -> None:
    accepted, rejections = run(proposal(action="merge"))
    assert accepted == []
    assert rejections[0].rule == "V0"


# ------------------------------------------------------------- the target


def target(ident: str = "I1") -> dict[str, InterpretationIn]:
    return {"I1": InterpretationIn(id=ident, kind="pattern", topic="work.decisions")}


def test_v7_attach_without_a_target_is_rejected() -> None:
    accepted, rejections = run(proposal(action="attach", ref=None))
    assert accepted == []
    assert rejections[0].rule == "V7"


def test_v8_an_unknown_target_is_rejected() -> None:
    accepted, rejections = run(proposal(action="attach", ref="I9"), targets=target())
    assert accepted == []
    assert rejections[0].rule == "V8"


def test_v9_a_denied_claim_cannot_be_attached_to_or_revised() -> None:
    policy = ValidationPolicy(denied_interpretation_ids=frozenset({"I1"}))
    for action in ("attach", "revise"):
        accepted, rejections = run(
            proposal(action=action, ref="I1"), policy=policy, targets=target()
        )
        assert accepted == []
        assert (rejections[0].rule, rejections[0].reason) == ("V9", "target_denied")


def test_v10_an_accepted_claim_is_not_rewritten_or_retired() -> None:
    policy = ValidationPolicy(accepted_interpretation_ids=frozenset({"I1"}))
    for action in ("revise", "retire"):
        accepted, rejections = run(
            proposal(action=action, ref="I1"), policy=policy, targets=target()
        )
        assert accepted == []
        assert (rejections[0].rule, rejections[0].reason) == ("V10", "target_accepted")


def test_an_accepted_claim_may_still_gain_evidence() -> None:
    policy = ValidationPolicy(accepted_interpretation_ids=frozenset({"I1"}))
    accepted, rejections = run(proposal(action="attach", ref="I1"), policy=policy, targets=target())
    assert rejections == []
    assert accepted[0].target_id == "I1"


def test_v6_an_attach_that_attaches_nothing_is_rejected() -> None:
    accepted, rejections = run(proposal(action="attach", ref="I1", evidence=[]), targets=target())
    assert accepted == []
    assert rejections[0].rule == "V6"


def test_retire_needs_no_evidence() -> None:
    accepted, rejections = run(proposal(action="retire", ref="I1", evidence=[]), targets=target())
    assert rejections == []
    assert accepted[0].action == "retire"


# ------------------------------------------------- the model's own refusals


def test_declined_items_are_normalised_for_the_ledger() -> None:
    batch = InterpretationBatch(
        declined=[
            Declined(about="Mentioned once.", reason="single_occurrence", signal_refs=["S1"]),
            Declined(about="Odd.", reason="because_i_said_so"),
        ]
    )
    items = validate_declined(batch)
    assert [(i.reason, i.rule) for i in items] == [
        ("single_occurrence", "M0_model_declined"),
        ("ambiguous", "M0_model_declined"),
    ]


# ------------------------------------------------------------- provenance


def draft(**kw) -> RecognitionDraft:
    base: dict = {
        "title": "You decide alone in the end",
        "body": "It looks like you gather opinions, then make the call yourself.",
        "explanation": "Twice this week you described asking around and then choosing on your own.",
        "cited_signal_refs": ["S1", "S2"],
    }
    base.update(kw)
    return RecognitionDraft(**base)


def prov_signal(ref: str, quote: str, **kw) -> SignalIn:
    return sig(ref, quote_text=quote, **kw)


META = {
    "msg-1": MessageMeta("msg-1", "conv-1", "Monday", seq=4, created_at=DAY1),
    "msg-2": MessageMeta("msg-2", "conv-1", "Tuesday", seq=9, created_at=DAY2),
}


def prov_case(**kw):
    s1 = prov_signal("1", "I asked everyone and then just did it my way")
    s2 = prov_signal(
        "2", "I took the decision on my own again", observed_at=DAY2, message_id="msg-2"
    )
    evidence = [
        EvidenceIn(signal=s1, role="supports", weight=kw.pop("w1", 0.6)),
        EvidenceIn(signal=s2, role="supports", weight=kw.pop("w2", 0.9)),
    ]
    return build_provenance(kw.pop("draft", draft()), evidence, {"S1": s1, "S2": s2}, META)


def test_provenance_snapshots_the_evidence_in_weight_order() -> None:
    result = prov_case()
    assert result.ok is True
    assert [r.signal_id for r in result.rows] == ["sig-2", "sig-1"]
    assert [r.display_order for r in result.rows] == [0, 1]
    assert result.rows[0].seq == 9
    assert result.rows[0].conversation_title == "Tuesday"
    assert result.rows[0].message_created_at == DAY2


def test_p1_a_card_needs_at_least_two_supporting_rows() -> None:
    s1 = prov_signal("1", "I asked everyone and then just did it my way")
    result = build_provenance(
        draft(cited_signal_refs=["S1"]),
        [EvidenceIn(signal=s1, role="supports")],
        {"S1": s1},
        META,
    )
    assert result.ok is False
    assert [v.rule for v in result.violations] == ["P1"]


def test_p2_the_card_may_not_repeat_a_quote_word_for_word() -> None:
    """Deleting the message has to really remove the user's words."""
    result = prov_case(draft=draft(body="You said: I took the decision on my own again."))
    assert result.ok is False
    assert [v.rule for v in result.violations] == ["P2"]
    assert "body" in result.violations[0].detail


def test_p2_is_not_fooled_by_swapping_a_curly_apostrophe() -> None:
    s1 = prov_signal("1", f"I don{chr(0x2019)}t hand the decision to anyone else")
    s2 = prov_signal("2", "I made that call by myself too", observed_at=DAY2, message_id="msg-2")
    result = build_provenance(
        draft(explanation="You wrote I don't hand the decision to anyone else."),
        [EvidenceIn(signal=s1), EvidenceIn(signal=s2)],
        {"S1": s1, "S2": s2},
        META,
    )
    assert [v.rule for v in result.violations] == ["P2"]


def test_a_paraphrase_passes() -> None:
    assert prov_case().ok is True


def test_a_citation_that_is_not_supporting_evidence_falls_back_to_all_supports() -> None:
    result = prov_case(draft=draft(cited_signal_refs=["S9"]))
    assert result.cited_fallback is True
    assert len(result.rows) == 2
    assert {v.rule for v in result.violations} == {"P4"}
    assert all(v.blocking is False for v in result.violations)


def test_a_valid_citation_narrows_the_snapshot() -> None:
    s1 = prov_signal("1", "I asked everyone and then just did it my way")
    s2 = prov_signal(
        "2", "I took the decision on my own again", observed_at=DAY2, message_id="msg-2"
    )
    s3 = prov_signal("3", "Same thing happened on Friday", observed_at=DAY2, message_id="msg-2")
    result = build_provenance(
        draft(cited_signal_refs=["S1", "S2"]),
        [EvidenceIn(signal=s) for s in (s1, s2, s3)],
        {"S1": s1, "S2": s2, "S3": s3},
        META,
    )
    assert result.cited_fallback is False
    assert [r.signal_id for r in result.rows] == ["sig-1", "sig-2"]


def test_ineligible_signals_never_reach_the_snapshot() -> None:
    s1 = prov_signal("1", "I asked everyone and then just did it my way")
    s2 = prov_signal("2", "My brother always decides for himself", subject="other")
    result = build_provenance(
        draft(), [EvidenceIn(signal=s1), EvidenceIn(signal=s2)], {"S1": s1, "S2": s2}, META
    )
    assert [r.signal_id for r in result.rows] == ["sig-1"]
    assert "P1" in {v.rule for v in result.violations}


def test_a_missing_message_is_recorded_without_blocking_the_card() -> None:
    s1 = prov_signal("1", "I asked everyone and then just did it my way")
    s2 = prov_signal("2", "I took the decision on my own again", message_id="msg-gone")
    result = build_provenance(
        draft(), [EvidenceIn(signal=s1), EvidenceIn(signal=s2)], {"S1": s1, "S2": s2}, META
    )
    assert result.ok is True
    assert [v.rule for v in result.violations] == ["P3"]
    assert result.rows[1].message_id == "msg-gone"
    assert result.rows[1].seq is None
