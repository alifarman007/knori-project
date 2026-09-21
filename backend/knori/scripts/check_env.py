"""Check a deployment's environment before anything is deployed onto it.

``deploy/scripts/deploy.sh`` runs this first, inside the image it is about to deploy::

    python -m knori.scripts.check_env

It answers one question: **would this .env produce a working, non-embarrassing
install?** It looks for three kinds of problem.

1. A required key is missing — nothing will start.
2. A key is still at the value ``.env.example`` ships with. ``SESSION_SECRET`` left at
   ``change-me-to-32-random-bytes`` is worse than a missing one, because everything
   comes up and looks fine.
3. A key is set to something that only makes sense on a laptop: a ``localhost``
   database, plain http URLs, ``DEBUG_PAYLOADS=true`` (which stores raw prompts and
   replies), or ``KNORI_DEV_NOW``, which freezes the clock.

The strictness depends on ``ENV``. On ``ENV=prod`` the third kind is an error; on a
laptop it is not mentioned at all.

Nothing here prints a value. The output names keys and says what is wrong with them,
so it is safe to paste into a chat.

    python -m knori.scripts.check_env                # read the current environment
    python -m knori.scripts.check_env --file ../.env # read a file instead
    python -m knori.scripts.check_env --env prod     # check as if this were production
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from knori.core.config import REPO_ROOT

EXAMPLE_FILE = REPO_ROOT / ".env.example"

#: Values that ship in .env.example or in the code as a stand-in. Any of them in a
#: production .env means somebody copied the file and stopped there.
PLACEHOLDERS: tuple[str, ...] = (
    "",
    "change-me",
    "change-me-to-32-random-bytes",
    "dev-secret-change-me",
    "changeme",
    "todo",
    "xxx",
    "your-key-here",
)


@dataclass(frozen=True, slots=True)
class Context:
    """The few values that decide what else is required."""

    env: str = "dev"
    llm_mode: str = "fake"
    signup_mode: str = "invite"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


Check = Callable[[str, Context], str | None]


@dataclass(frozen=True, slots=True)
class Rule:
    """What we expect of one variable."""

    key: str
    group: str
    why: str
    #: Required everywhere.
    required: bool = False
    #: Required only when ENV=prod.
    required_in_prod: bool = False
    #: Extra placeholder values, on top of :data:`PLACEHOLDERS`.
    placeholders: tuple[str, ...] = ()
    min_length: int = 0
    choices: tuple[str, ...] = ()
    #: Checked whenever a value is present.
    check: Check | None = None
    #: Checked only when ENV=prod.
    prod_check: Check | None = None


@dataclass(frozen=True, slots=True)
class Problem:
    key: str
    group: str
    message: str
    hint: str = ""


@dataclass(slots=True)
class Report:
    errors: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)
    unknown_keys: list[str] = field(default_factory=list)
    context: Context = field(default_factory=Context)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------- small checks


def _is_url(value: str, _: Context) -> str | None:
    if not value.startswith(("http://", "https://")):
        return "is not a URL (it must start with http:// or https://)"
    return None


def _https_in_prod(value: str, _: Context) -> str | None:
    if not value.startswith("https://"):
        return "must be https:// in production"
    return None


def _database_url(value: str, _: Context) -> str | None:
    if not value.startswith("postgresql+asyncpg://"):
        return "must start with postgresql+asyncpg:// (the app speaks asyncpg)"
    if "@" not in value:
        return "has no host part; expected postgresql+asyncpg://user:password@host:5432/knori"
    return None


def _database_url_in_prod(value: str, _: Context) -> str | None:
    host = value.rsplit("@", 1)[-1]
    if host.startswith(("localhost", "127.0.0.1")):
        return "points at localhost; inside compose the database is reachable as `db`"
    if ":knori@" in value or ":postgres@" in value:
        return "still uses the development password"
    return None


def _no_dev_clock(value: str, _: Context) -> str | None:
    if value.strip():
        return "freezes the clock; it must be empty in production"
    return None


def _false_in_prod(value: str, _: Context) -> str | None:
    if value.strip().lower() in {"1", "true", "yes", "on"}:
        return "stores raw prompts and replies; it must be false in production"
    return None


def _real_mail_host(value: str, _: Context) -> str | None:
    if value.strip().lower() in {"localhost", "127.0.0.1", "mailpit"}:
        return "points at the development mail catcher, so no mail leaves the machine"
    return None


def _sender_has_address(value: str, _: Context) -> str | None:
    if "@" not in value:
        return "has no email address in it"
    return None


def _sender_real_domain(value: str, _: Context) -> str | None:
    if value.rstrip(">").endswith((".local", ".localhost", ".example", ".invalid")):
        return "uses a fake domain, so real mail servers will reject it"
    return None


def _age_key(value: str, _: Context) -> str | None:
    if not value.startswith(("AGE-SECRET-KEY-1", "age1")):
        return "is not an age key. Make one with `age-keygen` and keep it in the password manager"
    return None


def _port(value: str, _: Context) -> str | None:
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        return "is not a port number"
    return None


def _positive_int(value: str, _: Context) -> str | None:
    if not value.isdigit() or int(value) < 1:
        return "must be a whole number of 1 or more"
    return None


def _domain(value: str, _: Context) -> str | None:
    if "/" in value or ":" in value:
        return "must be a bare hostname such as knori.app, with no scheme and no path"
    if "." not in value:
        return "does not look like a domain name"
    return None


def _email_address(value: str, _: Context) -> str | None:
    if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
        return "is not an email address"
    return None


# ---------------------------------------------------------------------------- rules

RULES: tuple[Rule, ...] = (
    # --- core ---------------------------------------------------------------
    Rule(
        "ENV",
        "core",
        "decides how strict everything else is",
        required=True,
        choices=("dev", "test", "prod"),
    ),
    Rule(
        "APP_URL",
        "core",
        "where the web app lives; used in links inside emails",
        required=True,
        check=_is_url,
        prod_check=_https_in_prod,
    ),
    Rule(
        "API_URL",
        "core",
        "where the API lives; decides whether cookies are Secure",
        required=True,
        check=_is_url,
        prod_check=_https_in_prod,
    ),
    Rule("LOG_LEVEL", "core", "how much is logged", choices=("debug", "info", "warning", "error")),
    Rule(
        "SESSION_SECRET",
        "core",
        "signing key reserved for sessions; must be unguessable",
        required=True,
        min_length=32,
    ),
    # --- database -----------------------------------------------------------
    Rule(
        "DATABASE_URL",
        "database",
        "the only stateful service there is",
        required=True,
        check=_database_url,
        prod_check=_database_url_in_prod,
    ),
    # --- the VPS stack (read by deploy/compose.prod.yml) ---------------------
    Rule(
        "KNORI_DOMAIN",
        "vps",
        "the domain Caddy gets a certificate for",
        required_in_prod=True,
        check=_domain,
    ),
    Rule(
        "ACME_EMAIL",
        "vps",
        "where Let's Encrypt sends expiry warnings",
        required_in_prod=True,
        check=_email_address,
    ),
    Rule("POSTGRES_USER", "vps", "database role the container creates on first boot"),
    Rule(
        "POSTGRES_PASSWORD",
        "vps",
        "password for that role; must match the one in DATABASE_URL",
        required_in_prod=True,
        placeholders=("knori", "postgres", "password"),
        min_length=12,
    ),
    Rule("POSTGRES_DB", "vps", "database name"),
    Rule("KNORI_IMAGE_API", "vps", "GHCR repository for the api image"),
    Rule("KNORI_IMAGE_WEB", "vps", "GHCR repository for the web image"),
    # --- models -------------------------------------------------------------
    Rule(
        "LLM_MODE",
        "models",
        "fake means no network and scripted replies",
        required=True,
        choices=("fake", "live"),
    ),
    Rule("ANTHROPIC_API_KEY", "models", "chat and all Recognition reasoning"),
    Rule("OPENAI_API_KEY", "models", "embeddings, and optionally GPT for chat"),
    Rule("OPENAI_REASONING_MODEL", "models", "which GPT answers reasoning tasks"),
    Rule("OPENAI_BACKGROUND_MODEL", "models", "which GPT answers background tasks"),
    Rule("DEBUG_PAYLOADS", "models", "raw request and response logging", prod_check=_false_in_prod),
    # --- jobs ---------------------------------------------------------------
    Rule("WORKER_CONCURRENCY", "jobs", "how many jobs run at once", check=_positive_int),
    Rule("KNORI_DEV_NOW", "jobs", "freezes the clock for demos", prod_check=_no_dev_clock),
    # --- signup -------------------------------------------------------------
    Rule(
        "SIGNUP_MODE",
        "signup",
        "invite keeps strangers out",
        required=True,
        choices=("invite", "open"),
    ),
    Rule("FIRST_INVITE_CODE", "signup", "the development invite code", placeholders=("KNORI-DEV",)),
    # --- email --------------------------------------------------------------
    Rule(
        "SMTP_HOST",
        "email",
        "verification and password-reset mail",
        required_in_prod=True,
        prod_check=_real_mail_host,
    ),
    Rule("SMTP_PORT", "email", "SMTP port", check=_port),
    Rule("SMTP_USER", "email", "SMTP username", required_in_prod=True),
    Rule("SMTP_PASSWORD", "email", "SMTP password", required_in_prod=True),
    Rule(
        "SMTP_FROM",
        "email",
        "the From: address users will see",
        required=True,
        check=_sender_has_address,
        prod_check=_sender_real_domain,
    ),
    Rule("SMTP_TLS", "email", "whether to use STARTTLS"),
    # --- backups ------------------------------------------------------------
    Rule(
        "S3_ENDPOINT", "backups", "S3-compatible endpoint for off-box dumps", required_in_prod=True
    ),
    Rule("S3_BUCKET", "backups", "bucket the dumps go into", required_in_prod=True),
    Rule("S3_ACCESS_KEY", "backups", "bucket access key", required_in_prod=True),
    Rule("S3_SECRET_KEY", "backups", "bucket secret key", required_in_prod=True),
    Rule(
        "BACKUP_KEY",
        "backups",
        "age key the dumps are encrypted with; without it a backup is unreadable",
        required_in_prod=True,
        check=_age_key,
    ),
    # --- ops ----------------------------------------------------------------
    Rule(
        "OPS_EMAIL",
        "ops",
        "where the alerts job sends warnings",
        required_in_prod=True,
        check=_email_address,
    ),
    Rule("HEALTHCHECK_PING_URL", "ops", "dead-man switch pinged by every backup", check=_is_url),
    Rule("SENTRY_DSN", "ops", "optional error reporting"),
)

RULES_BY_KEY: Mapping[str, Rule] = {rule.key: rule for rule in RULES}

GROUP_TITLES: Mapping[str, str] = {
    "core": "Core",
    "database": "Database",
    "vps": "The VPS stack (deploy/compose.prod.yml)",
    "models": "Models",
    "jobs": "Jobs",
    "signup": "Signup",
    "email": "Email",
    "backups": "Backups",
    "ops": "Ops",
}


# ------------------------------------------------------------------------ reading


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a .env file the way Docker Compose does.

    ``KEY=value``, optional ``export``, ``#`` starts a comment when it follows a space,
    and a value may be wrapped in single or double quotes.
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        stripped = value.strip()
        if stripped[:1] in {'"', "'"} and stripped[-1:] == stripped[:1] and len(stripped) >= 2:
            values[key] = stripped[1:-1]
            continue
        # An unquoted value ends at the first '#' that starts the value or follows a
        # space, so `KEY=   # note` is an empty value, not the note.
        values[key] = _strip_comment(value).strip()
    return values


def _strip_comment(value: str) -> str:
    for index, character in enumerate(value):
        if character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def example_keys() -> set[str]:
    """Every key .env.example documents. Empty when the file is not shipped."""
    if not EXAMPLE_FILE.is_file():
        return set()
    return set(parse_env_file(EXAMPLE_FILE))


# ---------------------------------------------------------------------- validating


def validate(values: Mapping[str, str], *, env: str | None = None) -> Report:
    """Check a set of values. Pure: it reads nothing but its arguments."""
    context = Context(
        env=(env or values.get("ENV") or "dev").strip().lower(),
        llm_mode=(values.get("LLM_MODE") or "fake").strip().lower(),
        signup_mode=(values.get("SIGNUP_MODE") or "invite").strip().lower(),
    )
    report = Report(context=context)

    for rule in RULES:
        value = (values.get(rule.key) or "").strip()
        required = rule.required or (rule.required_in_prod and context.is_prod)

        if not value:
            if required:
                report.errors.append(
                    Problem(rule.key, rule.group, "is missing", f"needed: {rule.why}")
                )
            continue

        lowered = value.lower()
        if lowered in PLACEHOLDERS or lowered in {p.lower() for p in rule.placeholders}:
            problem = Problem(
                rule.key,
                rule.group,
                "is still at its example value",
                f"{rule.why} - replace it before anyone real uses this install",
            )
            (report.errors if context.is_prod or required else report.warnings).append(problem)
            continue

        if rule.choices and lowered not in rule.choices:
            report.errors.append(
                Problem(rule.key, rule.group, f"must be one of: {', '.join(rule.choices)}")
            )
            continue

        if rule.min_length and len(value) < rule.min_length:
            report.errors.append(
                Problem(
                    rule.key,
                    rule.group,
                    f"is only {len(value)} characters; {rule.min_length} is the minimum",
                    "make one with: openssl rand -base64 32",
                )
            )
            continue

        # A prod_check is not run at all outside production: on a laptop "must be
        # https" is noise, not news.
        checks: list[Check] = [rule.check] if rule.check is not None else []
        if rule.prod_check is not None and context.is_prod:
            checks.append(rule.prod_check)
        for check in checks:
            message = check(value, context)
            if message is not None:
                report.errors.append(Problem(rule.key, rule.group, message, rule.why))
                break

    _check_live_mode(values, context, report)
    _check_password_matches_url(values, context, report)

    known = set(RULES_BY_KEY)
    report.unknown_keys = sorted(key for key in example_keys() if key not in known)
    return report


def _check_live_mode(values: Mapping[str, str], context: Context, report: Report) -> None:
    """A live install with no key starts up and then fails on the first message."""
    if context.llm_mode != "live":
        if context.is_prod:
            report.warnings.append(
                Problem(
                    "LLM_MODE",
                    "models",
                    "is 'fake' in production",
                    "chat will answer with scripted test replies, not a real model",
                )
            )
        return
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        if not (values.get(key) or "").strip():
            report.errors.append(
                Problem(key, "models", "is missing while LLM_MODE=live", "every model call fails")
            )


def _check_password_matches_url(
    values: Mapping[str, str], context: Context, report: Report
) -> None:
    """The two places the database password is written must agree, or the api cannot
    log in to the database the compose file just created."""
    password = (values.get("POSTGRES_PASSWORD") or "").strip()
    url = (values.get("DATABASE_URL") or "").strip()
    if not password or not url or "@" not in url:
        return
    credentials = url.rsplit("@", 1)[0]
    if ":" not in credentials.rsplit("/", 1)[-1]:
        return
    in_url = credentials.rsplit(":", 1)[-1]
    if in_url != password:
        problem = Problem(
            "DATABASE_URL",
            "database",
            "does not contain the password in POSTGRES_PASSWORD",
            "the api would be refused by the database the compose file creates",
        )
        (report.errors if context.is_prod else report.warnings).append(problem)


# -------------------------------------------------------------------------- output


def render(report: Report) -> str:
    lines: list[str] = []
    context = report.context
    lines.append(f"Checking environment: ENV={context.env}, LLM_MODE={context.llm_mode}")

    if report.errors:
        lines.append("")
        lines.append(f"{len(report.errors)} problem(s) that must be fixed:")
        lines.extend(_render_group(report.errors))

    if report.warnings:
        lines.append("")
        lines.append(f"{len(report.warnings)} thing(s) worth a look:")
        lines.extend(_render_group(report.warnings))

    if report.unknown_keys:
        lines.append("")
        lines.append(
            ".env.example documents keys this check does not know about, so they are "
            "unchecked: " + ", ".join(report.unknown_keys)
        )
        lines.append("  (add them to RULES in backend/knori/scripts/check_env.py)")

    lines.append("")
    if report.ok and not report.warnings:
        lines.append("All good.")
    elif report.ok:
        lines.append("No blocking problems.")
    else:
        lines.append("Not ready. Fix the problems above and run this again.")
    return "\n".join(lines)


def _render_group(problems: list[Problem]) -> list[str]:
    lines: list[str] = []
    seen_groups: set[str] = set()
    for problem in sorted(problems, key=lambda p: (p.group, p.key)):
        if problem.group not in seen_groups:
            seen_groups.add(problem.group)
            lines.append(f"  {GROUP_TITLES.get(problem.group, problem.group)}")
        lines.append(f"    {problem.key}  {problem.message}")
        if problem.hint:
            lines.append(f"      -> {problem.hint}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a .env before deploying. Never prints a value.",
    )
    parser.add_argument(
        "--file", type=Path, help="read this .env instead of the current environment"
    )
    parser.add_argument("--env", help="check as if ENV were this (dev, test or prod)")
    parser.add_argument("--warnings-as-errors", action="store_true", help="fail on warnings too")
    arguments = parser.parse_args(argv)

    if arguments.file is not None:
        if not arguments.file.is_file():
            print(f"no such file: {arguments.file}", file=sys.stderr)
            return 2
        values: Mapping[str, str] = parse_env_file(arguments.file)
    else:
        values = os.environ

    report = validate(values, env=arguments.env)
    print(render(report))
    if not report.ok:
        return 1
    if arguments.warnings_as_errors and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
