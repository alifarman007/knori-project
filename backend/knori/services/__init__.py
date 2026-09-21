"""Services: the work that happens between an HTTP request and the database.

Routers stay thin and the engine stays pure, so anything that is neither validation
nor a Recognition rule lives here. Each module is owned by one slice and imports
nothing from another service module, which keeps the import graph flat and stops a
missing slice from breaking the API.
"""

from __future__ import annotations
