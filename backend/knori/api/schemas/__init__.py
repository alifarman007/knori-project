"""Pydantic request and response models for the HTTP layer.

These are the API's contract with the web app: the OpenAPI document is generated
from them and ``frontend/lib/api.ts`` is generated from that. They are deliberately
separate from the SQLAlchemy models, so renaming a column never silently changes a
response, and no database field is exposed unless someone wrote it down here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for every schema in this package.

    ``extra="forbid"`` on input means a typo in a field name is a 422 the client can
    see, not a value silently ignored.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Accepted(ApiModel):
    """202 body for work that finished later, or that deliberately says nothing."""

    ok: bool = True
    detail: str = ""


__all__ = ["Accepted", "ApiModel"]
