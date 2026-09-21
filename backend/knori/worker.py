"""Entry point for the background worker: ``python -m knori.worker``.

Same image as the API (plan.md §3.1), different command.
"""

from __future__ import annotations

import sys

from knori.jobs.worker import main

if __name__ == "__main__":
    sys.exit(main())
