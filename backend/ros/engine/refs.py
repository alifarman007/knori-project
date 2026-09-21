"""Short ids the model sees, and the real ids it never does.

Every prompt talks about ``S12``, ``I3`` and ``M7``. The database talks about
UUIDs. This module is the only place the two meet.

Two reasons it matters, both from plan.md §4.3:

* **cost and clarity** — a UUID is 36 tokens of noise per mention;
* **safety** — a short id the model invented cannot be resolved, because a ref is
  only known if it was in *this* request, for *this* user. The caller looks a ref
  up here and rejects the item when the lookup fails (rule V2/V8). There is no
  path from a hallucinated ref to a row.

Refs are handed out in input order, starting at 1, so the same input always
produces the same prompt — which is what makes a failed run reproducible.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field

SIGNAL = "S"
INTERPRETATION = "I"
MESSAGE = "M"
PREFIXES = (SIGNAL, INTERPRETATION, MESSAGE)

_REF = re.compile(r"\A([A-Z])([0-9]+)\Z")


class UnknownRef(KeyError):
    """A ref that was not in the input. Never resolve one; reject the item."""

    def __init__(self, ref: str, prefix: str = "") -> None:
        super().__init__(ref)
        self.ref = ref
        self.prefix = prefix

    def __str__(self) -> str:
        where = f" (expected {self.prefix}n)" if self.prefix else ""
        return f"unknown ref {self.ref!r}{where}"


def parse_ref(value: str) -> tuple[str, int] | None:
    """``"S12"`` → ``("S", 12)``. ``None`` for anything else."""
    match = _REF.match((value or "").strip())
    if match is None:
        return None
    return match.group(1), int(match.group(2))


@dataclass(frozen=True, slots=True)
class RefMap:
    """One prefix's worth of ``short id ↔ real id``, in input order."""

    prefix: str
    by_ref: Mapping[str, str]
    by_id: Mapping[str, str]

    @classmethod
    def build(cls, prefix: str, ids: Iterable[object]) -> RefMap:
        """Number ``ids`` from 1, keeping order and ignoring repeats."""
        by_ref: dict[str, str] = {}
        by_id: dict[str, str] = {}
        for value in ids:
            real = str(value)
            if not real or real in by_id:
                continue
            ref = f"{prefix}{len(by_id) + 1}"
            by_id[real] = ref
            by_ref[ref] = real
        return cls(prefix=prefix, by_ref=by_ref, by_id=by_id)

    @classmethod
    def empty(cls, prefix: str) -> RefMap:
        return cls(prefix=prefix, by_ref={}, by_id={})

    def ref_for(self, real_id: object) -> str | None:
        return self.by_id.get(str(real_id))

    def id_for(self, ref: str) -> str | None:
        return self.by_ref.get((ref or "").strip())

    def resolve(self, ref: str) -> str:
        """The real id behind a ref, or :class:`UnknownRef`."""
        real = self.id_for(ref)
        if real is None:
            raise UnknownRef(ref, self.prefix)
        return real

    def known(self, ref: str) -> bool:
        return (ref or "").strip() in self.by_ref

    def refs(self) -> tuple[str, ...]:
        return tuple(self.by_ref)

    def ids(self) -> tuple[str, ...]:
        return tuple(self.by_id)

    def items(self) -> Iterator[tuple[str, str]]:
        return iter(self.by_ref.items())

    def __contains__(self, ref: object) -> bool:
        return isinstance(ref, str) and self.known(ref)

    def __len__(self) -> int:
        return len(self.by_ref)


@dataclass(frozen=True, slots=True)
class RefSet:
    """The three ref spaces one model call uses, built from what it was sent."""

    signals: RefMap = field(default_factory=lambda: RefMap.empty(SIGNAL))
    interpretations: RefMap = field(default_factory=lambda: RefMap.empty(INTERPRETATION))
    messages: RefMap = field(default_factory=lambda: RefMap.empty(MESSAGE))

    @classmethod
    def build(
        cls,
        *,
        signal_ids: Iterable[object] = (),
        interpretation_ids: Iterable[object] = (),
        message_ids: Iterable[object] = (),
    ) -> RefSet:
        return cls(
            signals=RefMap.build(SIGNAL, signal_ids),
            interpretations=RefMap.build(INTERPRETATION, interpretation_ids),
            messages=RefMap.build(MESSAGE, message_ids),
        )

    def for_prefix(self, prefix: str) -> RefMap:
        if prefix == SIGNAL:
            return self.signals
        if prefix == INTERPRETATION:
            return self.interpretations
        if prefix == MESSAGE:
            return self.messages
        raise UnknownRef(prefix)

    def resolve(self, ref: str) -> str:
        """Resolve any ref by its prefix. Unknown prefix, unknown ref, same answer."""
        parsed = parse_ref(ref)
        if parsed is None:
            raise UnknownRef(ref)
        try:
            table = self.for_prefix(parsed[0])
        except UnknownRef:
            raise UnknownRef(ref) from None
        return table.resolve(ref)


__all__ = [
    "INTERPRETATION",
    "MESSAGE",
    "PREFIXES",
    "SIGNAL",
    "RefMap",
    "RefSet",
    "UnknownRef",
    "parse_ref",
]
