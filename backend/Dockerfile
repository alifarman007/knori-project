# syntax=docker/dockerfile:1.7
# KnoRI API, worker and migrations — one image, three commands (plan.md §3.1, §9).
#
#   api        python -m uvicorn knori.main:app --host 0.0.0.0 --port 8000   (the CMD)
#   worker     python -m knori.worker
#   migrate    python -m alembic upgrade head
#
# The build context is `backend/`. The repository's `config/` directory is a second,
# named build context, because the application reads its tuning constants from it:
#
#   docker build -t knori-api -f backend/Dockerfile --build-context config=./config backend
#
# deploy/compose.demo.yml passes the same thing through build.additional_contexts, and
# .github/workflows/images.yml through build-contexts.
#
# Why the image mirrors the repository layout (/app/backend + /app/config) and the
# project is installed in editable mode: knori/core/config.py computes
# REPO_ROOT = Path(__file__).resolve().parents[3] and reads config/*.yaml and
# backend/alembic.ini from it, and backend/ros/llm/cost.py does the same. A plain
# site-packages install would make those paths resolve inside the interpreter's lib
# directory, and the app would start and then fail to find its own thresholds.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# ---------------------------------------------------------------- dependencies
# Only pyproject.toml is copied at this point, so this layer is rebuilt when the
# dependency list changes and not when application code changes. The list is read
# out of pyproject.toml rather than repeated here, so it cannot drift from it.
# Every runtime dependency ships a manylinux wheel for cp312, so no compiler and
# no libpq are needed (asyncpg speaks the wire protocol itself).
COPY pyproject.toml ./
RUN python -c "import tomllib;print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install --no-cache-dir -r /tmp/requirements.txt

# ---------------------------------------------------------------- application
COPY --from=config . /app/config
COPY . /app/backend

# --no-deps keeps the layer above the single source of installed versions; -e is
# deliberate, for the reason in the header note.
RUN pip install --no-cache-dir --no-deps -e .

# Reported by GET /version, so a reviewer can tell which commit is running.
ARG GIT_SHA=""
ENV GIT_SHA=${GIT_SHA}

# Nothing in the image writes to disk — all state is in Postgres.
RUN useradd --create-home --uid 10001 knori && chown -R knori:knori /app
USER knori

EXPOSE 8000

# urllib rather than curl, so the image needs no extra packages. The worker serves
# no HTTP, so compose turns this off for that service.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"]

CMD ["python", "-m", "uvicorn", "knori.main:app", "--host", "0.0.0.0", "--port", "8000"]
