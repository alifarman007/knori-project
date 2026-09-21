"""The HTTP layer: routers, request/response schemas and shared dependencies.

Nothing here holds business rules. A router validates input, calls a service or the
engine, and shapes the answer. Every authenticated route takes ``CurrentUser`` from
``knori.api.deps`` and every query underneath filters by that user's id, so no URL
or body ever carries a user id.
"""

from __future__ import annotations

API_PREFIX = "/api/v1"

__all__ = ["API_PREFIX"]
