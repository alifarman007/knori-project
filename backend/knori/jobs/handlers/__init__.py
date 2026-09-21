"""Job handlers.

``knori.jobs.registry.load_handlers`` imports every module in this package on worker
start-up, which is what makes the ``@job`` decorators run. Adding background work is
therefore a new module here and nothing else — the worker never needs editing.

This file imports nothing on purpose: each slice owns its own module, and one that
has not been written yet must not stop the others from loading.
"""

from __future__ import annotations
