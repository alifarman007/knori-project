"""Give an account the admin role, or take it away. Run by ``./run admin``.

Without this, nothing in the product ever sets ``users.role`` to ``admin``: signup
writes ``user`` and there is no screen that changes it. Every ``/api/v1/admin/*``
endpoint — the queue and cost pages, and the ledger showing why KnoRI did or did not
recognise something — is therefore unreachable on a fresh install, which is exactly
the part a reviewer wants to see.

    python -m knori.scripts.promote alex@knori.demo
    python -m knori.scripts.promote alex@knori.demo --demote
    python -m knori.scripts.promote --list

The change is written to ``audit_log`` like any other account action, with the actor
recorded as ``admin``, because granting yourself administrative access to other
people's data should leave a trace.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from knori.core.logging import configure_logging
from knori.db.models import User
from knori.db.session import dispose, session_scope
from knori.services.accounts import normalize_email, record_audit


async def _list_admins() -> int:
    async with session_scope() as session:
        rows = (
            await session.scalars(select(User).where(User.role == "admin").order_by(User.email))
        ).all()
    if not rows:
        print("No admin accounts. Grant one with: python -m knori.scripts.promote <email>")
        return 0
    print(f"{len(rows)} admin account(s):")
    for user in rows:
        print(f"  {user.email}  ({user.display_name}, {user.status})")
    return 0


async def _set_role(email: str, *, role: str) -> int:
    address = normalize_email(email)
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == address))
        if user is None:
            print(f"No account with the address {address!r}.", file=sys.stderr)
            return 1
        if user.role == role:
            print(f"{address} is already {role!r}. Nothing to do.")
            return 0

        previous, user.role = user.role, role
        await record_audit(
            session,
            action="role_changed",
            user_id=user.id,
            actor="admin",
            target_type="user",
            target_id=user.id,
            meta={"from": previous, "to": role, "by": "knori.scripts.promote"},
        )
    verb = "now an admin" if role == "admin" else "back to an ordinary user"
    print(f"{address} is {verb}.")
    if role == "admin":
        print("Sign out and back in for the change to reach the browser session.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m knori.scripts.promote",
        description="Grant or remove the admin role on an account.",
    )
    parser.add_argument("email", nargs="?", help="the account's email address")
    parser.add_argument(
        "--demote", action="store_true", help="remove the admin role instead of granting it"
    )
    parser.add_argument("--list", action="store_true", help="show the current admin accounts")
    args = parser.parse_args(argv)

    if not args.list and not args.email:
        parser.error("give an email address, or --list")

    configure_logging()

    async def run() -> int:
        # Dispose inside this loop: a pooled asyncpg connection closed after the loop
        # has gone belongs to nothing, and the teardown error it prints looks like a
        # failure when the command actually worked.
        try:
            if args.list:
                return await _list_admins()
            return await _set_role(args.email, role="user" if args.demote else "admin")
        except Exception as exc:  # a CLI should explain, not traceback
            print(f"Could not reach the database: {exc}", file=sys.stderr)
            print("Is it running? Try: ./run db", file=sys.stderr)
            return 1
        finally:
            await dispose()

    return asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
