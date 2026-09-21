"""The only place that reads the current time.

Every part of the app calls ``now()`` instead of ``datetime.now()`` so that tests and
demos can move time with ``KNORI_DEV_NOW`` (see plan.md §3.6). Recognition needs
evidence from two different days, so being able to fake time is what makes a demo
possible in one afternoon.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from knori.core.config import settings

_override: datetime | None = None


def _parse(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def now() -> datetime:
    """Current time as an aware UTC datetime."""
    if _override is not None:
        return _override
    if settings.env != "prod":
        from_env = _parse(settings.knori_dev_now)
        if from_env is not None:
            return from_env
    return datetime.now(UTC)


def today_in(tz_name: str) -> str:
    """Calendar date (YYYY-MM-DD) in the user's timezone — the unit R3 counts."""
    return now().astimezone(_zone(tz_name)).date().isoformat()


def local_date(moment: datetime, tz_name: str) -> str:
    return moment.astimezone(_zone(tz_name)).date().isoformat()


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


@contextmanager
def frozen(moment: datetime | str) -> Iterator[datetime]:
    """Freeze time inside a ``with`` block. Tests and the seed script use this."""
    global _override
    previous = _override
    parsed = _parse(moment) if isinstance(moment, str) else moment
    if parsed is None:
        raise ValueError(f"cannot parse time: {moment!r}")
    _override = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    try:
        yield _override
    finally:
        _override = previous


@contextmanager
def shifted(delta: timedelta) -> Iterator[datetime]:
    """Move time by a delta (used by the seed script to write past conversations)."""
    with frozen(now() + delta) as moment:
        yield moment
