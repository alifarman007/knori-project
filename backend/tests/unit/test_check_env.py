"""What ``check_env`` accepts and what it refuses.

The script is the last gate before a deploy, so the tests are about the two ways it
can be wrong: letting a broken .env through, and blocking a good one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knori.scripts import check_env

GOOD_PROD: dict[str, str] = {
    "ENV": "prod",
    "APP_URL": "https://knori.app",
    "API_URL": "https://knori.app",
    "LOG_LEVEL": "info",
    "SESSION_SECRET": "P4kq2Zt8mVx1Lr6Ns0Wb7Jy3Hd5Gf9Qc2Ae4Ui8",
    "DATABASE_URL": "postgresql+asyncpg://knori:s3cret-long-password@db:5432/knori",
    "KNORI_DOMAIN": "knori.app",
    "ACME_EMAIL": "ops@knori.app",
    "POSTGRES_USER": "knori",
    "POSTGRES_PASSWORD": "s3cret-long-password",
    "POSTGRES_DB": "knori",
    "LLM_MODE": "live",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "OPENAI_API_KEY": "sk-test",
    "DEBUG_PAYLOADS": "false",
    "KNORI_DEV_NOW": "",
    "SIGNUP_MODE": "invite",
    "FIRST_INVITE_CODE": "KNORI-BETA-2026",
    "SMTP_HOST": "smtp.postmarkapp.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "token",
    "SMTP_PASSWORD": "token",
    "SMTP_FROM": "KnoRI <hello@knori.app>",
    "S3_ENDPOINT": "https://s3.eu-central-1.example.com",
    "S3_BUCKET": "knori-backups",
    "S3_ACCESS_KEY": "AKIAEXAMPLE",
    "S3_SECRET_KEY": "secret",
    "BACKUP_KEY": "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ",
    "OPS_EMAIL": "ops@knori.app",
}


def failing_keys(report: check_env.Report) -> set[str]:
    return {problem.key for problem in report.errors}


def warning_keys(report: check_env.Report) -> set[str]:
    return {problem.key for problem in report.warnings}


# --------------------------------------------------------------------- the good case


def test_a_complete_production_env_passes() -> None:
    report = check_env.validate(GOOD_PROD)
    assert report.ok, report.errors
    assert report.warnings == []


def test_a_laptop_env_passes() -> None:
    report = check_env.validate(
        {
            "ENV": "dev",
            "APP_URL": "http://localhost:3000",
            "API_URL": "http://localhost:8000",
            "SESSION_SECRET": "a" * 32,
            "DATABASE_URL": "postgresql+asyncpg://knori:knori@localhost:55432/knori",
            "LLM_MODE": "fake",
            "SIGNUP_MODE": "invite",
            "SMTP_FROM": "KnoRI <hello@knori.local>",
        }
    )
    assert report.ok, report.errors


# ------------------------------------------------------------------- missing values


@pytest.mark.parametrize("key", ["ENV", "APP_URL", "API_URL", "SESSION_SECRET", "DATABASE_URL"])
def test_a_missing_required_key_fails_everywhere(key: str) -> None:
    values = dict(GOOD_PROD)
    values.pop(key)
    report = check_env.validate(values, env="dev")
    assert key in failing_keys(report)


@pytest.mark.parametrize(
    "key", ["KNORI_DOMAIN", "ACME_EMAIL", "POSTGRES_PASSWORD", "BACKUP_KEY", "OPS_EMAIL"]
)
def test_keys_only_the_vps_needs_fail_in_production_only(key: str) -> None:
    values = dict(GOOD_PROD)
    values.pop(key)
    assert key in failing_keys(check_env.validate(values))
    assert key not in failing_keys(check_env.validate(values, env="dev"))


# ---------------------------------------------------------------- leftover defaults


def test_the_example_session_secret_is_refused() -> None:
    values = dict(GOOD_PROD, SESSION_SECRET="change-me-to-32-random-bytes")
    assert "SESSION_SECRET" in failing_keys(check_env.validate(values))


def test_a_short_session_secret_is_refused() -> None:
    values = dict(GOOD_PROD, SESSION_SECRET="tooshort")
    assert "SESSION_SECRET" in failing_keys(check_env.validate(values))


def test_the_development_invite_code_is_refused_in_production() -> None:
    values = dict(GOOD_PROD, FIRST_INVITE_CODE="KNORI-DEV")
    assert "FIRST_INVITE_CODE" in failing_keys(check_env.validate(values))


def test_the_development_database_password_is_refused_in_production() -> None:
    values = dict(
        GOOD_PROD,
        POSTGRES_PASSWORD="knori",
        DATABASE_URL="postgresql+asyncpg://knori:knori@db:5432/knori",
    )
    assert "POSTGRES_PASSWORD" in failing_keys(check_env.validate(values))


# ------------------------------------------------------------- laptop values in prod


def test_a_localhost_database_is_refused_in_production() -> None:
    values = dict(GOOD_PROD, DATABASE_URL="postgresql+asyncpg://knori:pw@localhost:5432/knori")
    assert "DATABASE_URL" in failing_keys(check_env.validate(values))


def test_plain_http_urls_are_refused_in_production() -> None:
    values = dict(GOOD_PROD, APP_URL="http://knori.app")
    assert "APP_URL" in failing_keys(check_env.validate(values))
    assert "APP_URL" not in failing_keys(check_env.validate(values, env="dev"))


def test_debug_payloads_must_be_off_in_production() -> None:
    values = dict(GOOD_PROD, DEBUG_PAYLOADS="true")
    assert "DEBUG_PAYLOADS" in failing_keys(check_env.validate(values))


def test_a_frozen_clock_is_refused_in_production() -> None:
    values = dict(GOOD_PROD, KNORI_DEV_NOW="2026-09-21T10:00:00Z")
    assert "KNORI_DEV_NOW" in failing_keys(check_env.validate(values))


def test_the_development_mail_catcher_is_refused_in_production() -> None:
    values = dict(GOOD_PROD, SMTP_HOST="localhost")
    assert "SMTP_HOST" in failing_keys(check_env.validate(values))


def test_a_fake_sender_domain_is_refused_in_production() -> None:
    values = dict(GOOD_PROD, SMTP_FROM="KnoRI <hello@knori.local>")
    assert "SMTP_FROM" in failing_keys(check_env.validate(values))


def test_a_backup_key_that_is_not_an_age_key_is_refused() -> None:
    values = dict(GOOD_PROD, BACKUP_KEY="hunter2")
    assert "BACKUP_KEY" in failing_keys(check_env.validate(values))


def test_an_age_recipient_is_accepted_as_a_backup_key() -> None:
    values = dict(GOOD_PROD, BACKUP_KEY="age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq")
    assert "BACKUP_KEY" not in failing_keys(check_env.validate(values))


# --------------------------------------------------------------- cross-key checks


def test_live_mode_without_keys_fails() -> None:
    values = dict(GOOD_PROD)
    values["ANTHROPIC_API_KEY"] = ""
    report = check_env.validate(values)
    assert "ANTHROPIC_API_KEY" in failing_keys(report)


def test_fake_mode_in_production_is_only_a_warning() -> None:
    values = dict(GOOD_PROD, LLM_MODE="fake")
    report = check_env.validate(values)
    assert report.ok
    assert "LLM_MODE" in warning_keys(report)


def test_the_password_must_be_the_same_in_both_places() -> None:
    values = dict(GOOD_PROD, POSTGRES_PASSWORD="something-else-entirely")
    assert "DATABASE_URL" in failing_keys(check_env.validate(values))


def test_a_mismatch_is_only_a_warning_on_a_laptop() -> None:
    values = dict(GOOD_PROD, ENV="dev", POSTGRES_PASSWORD="something-else-entirely")
    report = check_env.validate(values, env="dev")
    assert "DATABASE_URL" in warning_keys(report)


def test_an_unknown_choice_is_refused() -> None:
    values = dict(GOOD_PROD, SIGNUP_MODE="everyone")
    assert "SIGNUP_MODE" in failing_keys(check_env.validate(values))


# ---------------------------------------------------------------------- the parser


def test_it_reads_a_dotenv_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "ENV=prod",
                "export APP_URL=https://knori.app",
                'SMTP_FROM="KnoRI <hello@knori.app>"',
                "SMTP_PORT=587            # the submission port",
                "BACKUP_KEY=              # filled in on the VPS",
                "SESSION_SECRET='quoted value'",
            ]
        ),
        encoding="utf-8",
    )
    values = check_env.parse_env_file(path)
    assert values["ENV"] == "prod"
    assert values["APP_URL"] == "https://knori.app"
    assert values["SMTP_FROM"] == "KnoRI <hello@knori.app>"
    assert values["SMTP_PORT"] == "587"
    assert values["BACKUP_KEY"] == ""
    assert values["SESSION_SECRET"] == "quoted value"


def test_a_hash_inside_a_quoted_value_is_kept(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('SESSION_SECRET="abc#def"\n', encoding="utf-8")
    assert check_env.parse_env_file(path)["SESSION_SECRET"] == "abc#def"


def test_the_shipped_example_file_parses() -> None:
    """If .env.example stops parsing, every deploy check becomes meaningless."""
    if not check_env.EXAMPLE_FILE.is_file():
        pytest.skip("no .env.example in this checkout")
    values = check_env.parse_env_file(check_env.EXAMPLE_FILE)
    assert values["ENV"] == "dev"
    assert values["LLM_MODE"] == "fake"


# ---------------------------------------------------------------------- the output


def test_the_report_never_prints_a_value() -> None:
    secret = "sup3r-secret-value-nobody-should-see"
    values = dict(GOOD_PROD, SESSION_SECRET=secret, POSTGRES_PASSWORD=secret)
    text = check_env.render(check_env.validate(values))
    assert secret not in text


def test_the_report_names_every_broken_key() -> None:
    values = dict(GOOD_PROD)
    values.pop("BACKUP_KEY")
    values["APP_URL"] = "http://knori.app"
    text = check_env.render(check_env.validate(values))
    assert "BACKUP_KEY" in text
    assert "APP_URL" in text
    assert "Not ready" in text


def test_main_returns_zero_for_a_good_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{k}={v}" for k, v in GOOD_PROD.items()), encoding="utf-8")
    assert check_env.main(["--file", str(path)]) == 0


def test_main_returns_one_for_a_broken_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("ENV=prod\n", encoding="utf-8")
    assert check_env.main(["--file", str(path)]) == 1


def test_main_returns_two_when_the_file_is_not_there(tmp_path: Path) -> None:
    assert check_env.main(["--file", str(tmp_path / "nope.env")]) == 2


def test_warnings_can_be_made_fatal(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    values = dict(GOOD_PROD, LLM_MODE="fake")
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()), encoding="utf-8")
    assert check_env.main(["--file", str(path)]) == 0
    assert check_env.main(["--file", str(path), "--warnings-as-errors"]) == 1
