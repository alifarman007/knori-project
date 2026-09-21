"""The eval corpus: personas with labels attached.

An eval persona is a demo persona (``knori.scripts.seed``) with two extra
sections:

* ``expected`` — the observations KnoRI is supposed to reach, each with the
  message ids that must appear as evidence behind it;
* ``traps`` — the things that look like observations and must not become cards,
  each naming the rule that is supposed to stop it.

Keeping one format for both means a persona can be loaded into a live demo
account with ``./run seed`` and scored with ``./run eval`` without being written
twice, and it means the thing being measured is the thing being shown.

The rule vocabulary in ``expect_rule`` is wider than the threshold's R0-R10,
because not every refusal is a threshold decision. A signal about somebody else
never reaches the interpreter at all — it is filtered out of the input by
``EngineRepo.new_signals`` (plan §4.3) — so there is no rule id for it and one is
defined here instead:

``F_subject``
    No signal from those messages was ``subject=self``, so the interpreter never
    saw them.
``F_sensitive``
    Every signal from those messages carried a sensitive category, same filter.
``M0_model_declined``
    The interpreter itself refused; the reason is in ``threshold_evaluations``.
``V0`` to ``V15``
    Code rejected the proposal before it was written (``ros.engine.validate``).
``R0`` to ``R10``
    ``thr-v1`` blocked it; the rule and every rule it evaluated are in the ledger.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evals.metrics import GoldExpectation, TrapExpectation
from knori.scripts.seed import Persona, SeedError, parse_persona, validate

CORPUS_DIR = Path(__file__).resolve().parent / "personas"

#: Pre-interpreter filters, named here because they are not threshold rules.
FILTER_RULES = ("F_subject", "F_sensitive")

#: The trap kinds plan §10 asks for, and what counts as the right reason for each.
#: A persona file may narrow or widen this with its own ``expect_rule``.
TRAP_RULES: Mapping[str, tuple[str, ...]] = {
    # Said once. The interpreter should decline it; if it proposes anyway, R3's
    # hard minimum is the backstop.
    "single_mention": ("M0_model_declined", "R3"),
    # Two calendar days, but one sitting either side of midnight: R3 also requires
    # twelve hours between the earliest and latest support.
    "one_sitting": ("R3",),
    # "If I ever moved abroad" is not something the user does.
    "hypothetical": ("F_subject", "M0_model_declined"),
    # Somebody else's words, even when the user agrees with them.
    "quoting_others": ("F_subject", "M0_model_declined", "V1"),
    # Venting and sarcasm are extracted weakly, so the score never reaches the bar.
    "sarcasm": ("M0_model_declined", "R8"),
    # Repeating back what the user just typed is not an observation.
    "trivial": ("M0_model_declined",),
    # R6 categories: stored because the user said it, never reasoned from.
    "sensitive": ("F_sensitive", "R6", "M0_model_declined"),
    # Already an explicit fact on the memory page — a Recognition would be a
    # parrot, and R2 says so.
    "already_known": ("R2", "M0_model_declined"),
    # The user rejected this claim once. R7 keeps it away.
    "prior_rejection": ("R7", "M0_model_declined"),
}

ALL_RULES: frozenset[str] = frozenset(
    [
        *FILTER_RULES,
        "M0_model_declined",
        *(f"R{n}" for n in range(11)),
        *(f"V{n}" for n in range(16)),
    ]
)


@dataclass(frozen=True, slots=True)
class EvalPersona:
    """One persona plus its labels."""

    persona: Persona
    gold: tuple[GoldExpectation, ...] = ()
    traps: tuple[TrapExpectation, ...] = ()

    @property
    def name(self) -> str:
        return self.persona.name

    @property
    def summary(self) -> str:
        return self.persona.summary

    def sensitive_refs(self) -> tuple[str, ...]:
        """Persona message ids carrying a sensitive signal — nothing may cite these."""
        return tuple(
            message.id
            for message, signal in self.persona.signals()
            if signal.sensitive
            # A message can hold both; only a message whose every signal is
            # sensitive is off limits as a whole.
            and all(s.sensitive for s in message.signals)
        )

    def filtered(self) -> dict[str, str]:
        """Message id → why nothing from it could reach the interpreter.

        Worked out from the persona itself rather than from the run: these are the
        filters in ``EngineRepo.new_signals``, and a corpus that could not predict
        them would not be able to say what a trap was testing.
        """
        out: dict[str, str] = {}
        for message in self.persona.messages():
            if not message.signals:
                continue
            if all(s.sensitive for s in message.signals):
                out[message.id] = "F_sensitive"
            elif all(s.subject != "self" for s in message.signals):
                out[message.id] = "F_subject"
        return out


def _gold(raw: Mapping[str, Any], index: int) -> GoldExpectation:
    identifier = str(raw.get("id") or f"g{index + 1}")
    gist = raw.get("gist")
    if not gist:
        raise SeedError(f"expected {identifier}: needs a `gist`")
    evidence = raw.get("evidence") or ()
    return GoldExpectation(
        id=identifier,
        gist=str(gist),
        evidence=tuple(str(item) for item in evidence),
        note=str(raw.get("note") or ""),
    )


def _trap(raw: Mapping[str, Any], index: int) -> TrapExpectation:
    identifier = str(raw.get("id") or f"t{index + 1}")
    kind = str(raw.get("kind") or "")
    if kind not in TRAP_RULES:
        known = ", ".join(sorted(TRAP_RULES))
        raise SeedError(f"trap {identifier}: kind {kind!r} is not one of {known}")
    declared = raw.get("expect_rule")
    if isinstance(declared, str):
        rules: tuple[str, ...] = (declared,)
    elif declared:
        rules = tuple(str(item) for item in declared)
    else:
        rules = TRAP_RULES[kind]
    return TrapExpectation(
        id=identifier,
        kind=kind,
        about=str(raw.get("about") or ""),
        expect_rule=rules,
        messages=tuple(str(item) for item in raw.get("messages") or ()),
    )


def parse_eval_persona(raw: Mapping[str, Any], *, source: Path | None = None) -> EvalPersona:
    persona = parse_persona(raw, source=source)
    return EvalPersona(
        persona=persona,
        gold=tuple(
            _gold(item, index)
            for index, item in enumerate(raw.get("expected") or ())
            if isinstance(item, Mapping)
        ),
        traps=tuple(
            _trap(item, index)
            for index, item in enumerate(raw.get("traps") or ())
            if isinstance(item, Mapping)
        ),
    )


def load(path: Path) -> EvalPersona:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SeedError(f"{path.name}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise SeedError(f"{path.name}: the file must contain a mapping")
    try:
        return parse_eval_persona(raw, source=path)
    except SeedError as exc:
        raise SeedError(f"{path.name}: {exc}") from exc


def paths(directory: Path = CORPUS_DIR) -> list[Path]:
    return sorted(directory.glob("*.yaml"))


def load_corpus(directory: Path = CORPUS_DIR, *, names: Sequence[str] = ()) -> list[EvalPersona]:
    """Every persona in the corpus, or just the named ones, in file order."""
    wanted = set(names)
    found = [load(path) for path in paths(directory) if not wanted or path.stem in wanted]
    missing = wanted - {item.name for item in found}
    if missing:
        known = ", ".join(path.stem for path in paths(directory)) or "none"
        raise SeedError(f"no persona called {', '.join(sorted(missing))}. Available: {known}")
    return found


def validate_corpus(item: EvalPersona, *, topics: Sequence[str] = ()) -> list[str]:
    """Everything wrong with one eval persona, as plain sentences.

    Runs the persona checks first (quotes really in their messages, topics in the
    taxonomy, cards that do not copy a quote) and then the label checks, which are
    what stop an eval from quietly measuring nothing: a gold label whose evidence
    does not exist, or a trap whose expected rule could never fire.
    """
    problems = validate(item.persona, topics=topics)
    ids = {message.id for message in item.persona.messages()}

    for gold in item.gold:
        if not gold.evidence:
            problems.append(f"expected {gold.id}: needs the message ids that must be cited")
        for ref in gold.evidence:
            if ref not in ids:
                problems.append(f"expected {gold.id}: {ref!r} is not a message in this file")

    seen: set[str] = set()
    for trap in item.traps:
        if trap.id in seen:
            problems.append(f"trap {trap.id}: duplicate id")
        seen.add(trap.id)
        if not trap.messages:
            problems.append(f"trap {trap.id}: needs the message ids the trap lives in")
        for ref in trap.messages:
            if ref not in ids:
                problems.append(f"trap {trap.id}: {ref!r} is not a message in this file")
        unknown = [rule for rule in trap.expect_rule if rule not in ALL_RULES]
        if unknown:
            problems.append(f"trap {trap.id}: unknown rule ids {unknown}")

    claimed = {ref for gold in item.gold for ref in gold.evidence}
    trapped = {ref for trap in item.traps for ref in trap.messages}
    overlap = sorted(claimed & trapped)
    if overlap:
        problems.append(
            "the same messages are cited as evidence and as a trap, so the two "
            f"cannot both be scored: {overlap}"
        )
    return problems


def validate_or_raise(item: EvalPersona, *, topics: Sequence[str] = ()) -> None:
    problems = validate_corpus(item, topics=topics)
    if problems:
        name = item.persona.source.name if item.persona.source else item.name
        raise SeedError(f"{name} is not usable:\n  " + "\n  ".join(problems))


__all__ = [
    "ALL_RULES",
    "CORPUS_DIR",
    "FILTER_RULES",
    "TRAP_RULES",
    "EvalPersona",
    "load",
    "load_corpus",
    "parse_eval_persona",
    "paths",
    "validate_corpus",
    "validate_or_raise",
]
