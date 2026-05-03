"""
PharmaFlow AI — entrypoint for uvicorn and Cloud Run.

Start locally:
    uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000

The real application is wired in scripts/app.py. This file exists so that
uvicorn can be invoked as `uvicorn app:app` from the repo root without
needing to know the internal package structure.
"""

from scripts.app import app  # noqa: F401  (re-exported for uvicorn)
