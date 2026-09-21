"""The account lifecycle end to end, against a real Postgres.

One test walks the whole path a first user takes: invite → register → verify →
onboarding (three answers written as real messages) → export → delete → undo. A
second one finishes the deletion and proves the promise on the privacy page: after a
purge, **no table that has a ``user_id`` still has a row for that user**, and the two
tables we keep have theirs set to NULL.

The list of tables is not written down here. It is derived from the schema, the same
way ``purge_user`` derives it, so a table added next month is checked the day it is
added and neither side can be updated without the other.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from knori.core.config import settings
from knori.core.rate_limit import get_rate_limiter
from knori.db.session import session_scope
from knori.services.export_delete import ANONYMISED_TABLES, purge_user, user_owned_tables
from knori.services.invites import create_invite
from tests.conftest import require_database

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
CSRF_HEADERS = {"X-Requested-With": "knori", "Origin": settings.app_url}
API = "/api/v1"


# --------------------------------------------------------------- no database needed


def test_purge_derives_its_table_list_from_the_schema() -> None:
    """Pure check: the rule is "has user_id", with exactly two documented exceptions."""
    tables = user_owned_tables()
    for expected in ("messages", "signals", "recognitions", "jobs", "auth_sessions"):
        assert expected in tables, f"{expected} would survive a purge"
    for kept in ANONYMISED_TABLES:
        assert kept not in tables
    assert "users" not in tables  # deleted by primary key, after the rest


# ------------------------------------------------------------------------- fixtures


def build_app() -> FastAPI:
    """The real app, middleware and all — including the CSRF check these calls must pass."""
    from knori.main import create_app

    return create_app()


async def _schema_is_migrated() -> bool:
    async with session_scope() as session:
        return bool(await session.scalar(text("SELECT to_regclass('public.users')")))


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[AsyncClient]:
    await require_database(database_url)
    if not await _schema_is_migrated():
        pytest.skip("database has no schema - run `./run migrate`")
    # One process-wide limiter; a second run in the same session would otherwise
    # trip the 5-registrations-per-hour rule.
    get_rate_limiter().reset()
    transport = ASGITransport(app=build_app(), client=("127.0.0.1", 9000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def invite_code() -> str:
    async with session_scope() as session:
        row = await create_invite(session, note="integration test", max_uses=5)
        return row.code


def unique_email() -> str:
    return f"flow-{uuid.uuid4().hex[:12]}@example.com"


async def _queued_token(user_id: uuid.UUID, kind: str) -> str:
    """Read the token out of the queued ``send_email`` job.

    This doubles as proof that the mail was enqueued in the same transaction as the
    account change: if the job is not there, the sign-up did not really finish.
    """
    async with session_scope() as session:
        value = await session.scalar(
            text(
                """
                SELECT payload -> 'context' ->> 'token'
                  FROM jobs
                 WHERE kind = 'send_email' AND user_id = :user_id
                   AND payload ->> 'kind' = :kind
                 ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"user_id": user_id, "kind": kind},
        )
    assert value, f"no queued {kind} email for {user_id}"
    return str(value)


async def _cleanup(user_id: uuid.UUID) -> None:
    async with session_scope() as session:
        await purge_user(session, user_id)


# ------------------------------------------------------------------------ the flow


async def test_signup_onboarding_export_delete_and_undo(
    client: AsyncClient, invite_code: str
) -> None:
    email = unique_email()
    user_id: uuid.UUID | None = None
    try:
        created = await client.post(
            f"{API}/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": "Alex",
                "invite_code": invite_code,
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        user_id = uuid.UUID(body["user_id"])
        assert body["email_verified"] is False
        assert "knori_session" in client.cookies

        token = await _queued_token(user_id, "verify")
        confirmed = await client.post(
            f"{API}/auth/verify-email", json={"token": token}, headers=CSRF_HEADERS
        )
        assert confirmed.status_code == 200, confirmed.text

        # A used token cannot be replayed.
        replay = await client.post(
            f"{API}/auth/verify-email", json={"token": token}, headers=CSRF_HEADERS
        )
        assert replay.status_code == 400

        me = (await client.get(f"{API}/me")).json()
        assert me["user"]["email_verified"] is True
        assert me["onboarding"]["current_step"] == 1
        assert me["settings"]["max_recognitions_per_day"] == 2

        step_one = await client.post(
            f"{API}/onboarding/answer",
            json={"step": 1, "text": "Alex", "timezone": "Europe/Berlin"},
            headers=CSRF_HEADERS,
        )
        assert step_one.status_code == 200, step_one.text
        assert step_one.json()["current_step"] == 2

        step_two = await client.post(
            f"{API}/onboarding/answer", json={"step": 2, "text": ""}, headers=CSRF_HEADERS
        )
        assert step_two.json()["step_2_done"] is True

        answers = [
            "I moved cities in March and I am still finding my feet.",
            "Notice how I spend my evenings. Leave my health out of it.",
            "Short sentences please, and no cheerleading.",
        ]
        for index, answer in enumerate(answers, start=1):
            state = await client.post(
                f"{API}/onboarding/answer",
                json={"step": 3, "text": answer},
                headers=CSRF_HEADERS,
            )
            assert state.status_code == 200, state.text
            assert state.json()["answers_given"] == index

        fourth = await client.post(
            f"{API}/onboarding/answer",
            json={"step": 3, "text": "one more"},
            headers=CSRF_HEADERS,
        )
        assert fourth.status_code == 409

        done = await client.post(f"{API}/onboarding/complete", headers=CSRF_HEADERS)
        assert done.status_code == 202, done.text
        assert set(done.json()["jobs_enqueued"]) == {"onboarding_parse", "compile_profile"}

        export = await client.get(f"{API}/me/export")
        assert export.status_code == 200
        assert "attachment" in export.headers["content-disposition"]
        data = export.json()
        assert data["account"]["email"] == email.lower()
        user_messages = [m for m in data["messages"] if m["role"] == "user"]
        assert [m["content"] for m in user_messages] == answers
        assert data["conversations"][0]["kind"] == "onboarding"

        gone = await client.request(
            "DELETE", f"{API}/me", json={"password": PASSWORD}, headers=CSRF_HEADERS
        )
        assert gone.status_code == 202, gone.text
        assert gone.json()["purge_after"]

        # Every session was revoked, so the old cookie is dead even if it is replayed.
        assert (await client.get(f"{API}/me")).status_code == 401

        back = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
        assert back.status_code == 200, back.text
        undone = await client.post(f"{API}/me/undelete", headers=CSRF_HEADERS)
        assert undone.status_code == 200, undone.text
        assert undone.json()["status"] == "active"
        assert (await client.get(f"{API}/me")).json()["user"]["status"] == "active"
    finally:
        if user_id is not None:
            await _cleanup(user_id)


async def test_bad_password_is_refused_the_same_way_as_a_bad_address(
    client: AsyncClient, invite_code: str
) -> None:
    email = unique_email()
    created = await client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": "Sam",
            "invite_code": invite_code,
        },
    )
    user_id = uuid.UUID(created.json()["user_id"])
    try:
        # The client still carries the session cookie from registering, so these POSTs
        # need the CSRF header like every other state-changing call from the app.
        wrong_password = await client.post(
            f"{API}/auth/login",
            json={"email": email, "password": "not the password"},
            headers=CSRF_HEADERS,
        )
        no_such_user = await client.post(
            f"{API}/auth/login",
            json={"email": unique_email(), "password": "not the password"},
            headers=CSRF_HEADERS,
        )
        assert wrong_password.status_code == no_such_user.status_code == 401
        assert wrong_password.json()["detail"] == no_such_user.json()["detail"]
        assert wrong_password.json()["code"] == "bad_credentials"
    finally:
        await _cleanup(user_id)


async def test_admin_pages_are_closed_to_ordinary_users(
    client: AsyncClient, invite_code: str
) -> None:
    created = await client.post(
        f"{API}/auth/register",
        json={
            "email": unique_email(),
            "password": PASSWORD,
            "display_name": "Sam",
            "invite_code": invite_code,
        },
    )
    user_id = uuid.UUID(created.json()["user_id"])
    try:
        for path in ("/admin/ops", "/admin/costs", f"/admin/decisions?user_id={user_id}"):
            assert (await client.get(f"{API}{path}")).status_code == 403
    finally:
        await _cleanup(user_id)


# ----------------------------------------------------------------------- the purge


async def test_purge_leaves_no_row_behind(client: AsyncClient, invite_code: str) -> None:
    email = unique_email()
    created = await client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": "Robin",
            "invite_code": invite_code,
        },
    )
    assert created.status_code == 201, created.text
    user_id = uuid.UUID(created.json()["user_id"])

    # Give the account something in as many tables as this slice can reach.
    await client.post(
        f"{API}/onboarding/answer",
        json={"step": 1, "text": "Robin", "timezone": "UTC"},
        headers=CSRF_HEADERS,
    )
    await client.post(
        f"{API}/onboarding/answer", json={"step": 2, "text": ""}, headers=CSRF_HEADERS
    )
    await client.post(
        f"{API}/onboarding/answer",
        json={"step": 3, "text": "Something worth remembering."},
        headers=CSRF_HEADERS,
    )
    await client.post(f"{API}/onboarding/complete", headers=CSRF_HEADERS)

    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO llm_calls (id, user_id, task, provider, model, status)
                VALUES (gen_random_uuid(), :user_id, 'chat.reply', 'fake', 'fake-1', 'ok')
                """
            ),
            {"user_id": user_id},
        )

    async with session_scope() as session:
        before = await _count_everywhere(session, user_id)
    assert before["messages"] > 0
    assert before["audit_log"] > 0
    assert before["llm_calls"] > 0

    async with session_scope() as session:
        report = await purge_user(session, user_id)
    assert report.deleted["users"] == 1

    async with session_scope() as session:
        after = await _count_everywhere(session, user_id)
        user_rows = await session.scalar(
            text("SELECT count(*) FROM users WHERE id = :user_id"), {"user_id": user_id}
        )
        kept = {
            table: await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE user_id IS NULL"),
            )
            for table in ANONYMISED_TABLES
        }

    left_over = {table: count for table, count in after.items() if count}
    assert left_over == {}, f"purge left rows behind: {left_over}"
    assert user_rows == 0
    # The kept tables still hold their rows; they simply no longer say who.
    assert all(count > 0 for count in kept.values())


async def _count_everywhere(session: Any, user_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in (*user_owned_tables(), *ANONYMISED_TABLES):
        counts[table] = int(
            await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            or 0
        )
    return counts
