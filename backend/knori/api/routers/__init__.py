"""One module per area of the API.

``knori.main`` mounts these by name (``from knori.api.routers import auth, me, ...``).
That works at runtime for any submodule, but a type checker only accepts names the
package actually exports — so they are imported here, in one place, rather than every
module guessing. The app factory needs all of them anyway: a missing router is a
broken build, not something to paper over.
"""

from __future__ import annotations

from knori.api.routers import (
    admin,
    auth,
    conversations,
    events,
    health,
    me,
    memory,
    onboarding,
    recognitions,
)

__all__ = [
    "admin",
    "auth",
    "conversations",
    "events",
    "health",
    "me",
    "memory",
    "onboarding",
    "recognitions",
]
