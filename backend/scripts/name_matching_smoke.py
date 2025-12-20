"""
Lightweight smoke checks for name matching behavior.

Run from repo root:
  python backend/scripts/name_matching_smoke.py
"""

from __future__ import annotations

import os
import sys


def _ensure_backend_on_path() -> None:
    # Allow `from app...` imports when running this file directly.
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.abspath(os.path.join(scripts_dir, ".."))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


def main() -> int:
    _ensure_backend_on_path()

    try:
        from app.services.name_matching import name_similarity_ratio  # noqa: WPS433 (local import)
    except ModuleNotFoundError as e:
        # Common case when running outside the backend venv/container.
        print(f"Missing dependency: {e}.")
        print("Install backend deps, e.g.:")
        print("  pip install -r backend/requirements.txt")
        return 2

    def check(a: str, b: str) -> float:
        score = name_similarity_ratio(a, b)
        print(f"{score:.3f}  |  {a!r}  vs  {b!r}")
        return score

    ok = True

    # Positive cases
    ok &= check("Dr. Strange", "Doctor Strange") >= 0.80
    ok &= check("Uzumaki Naruto", "Naruto Uzumaki") >= 0.80

    # Negative-ish case (should NOT be considered the same character)
    ok &= check("Doctor Strange", "Doctor Doom") < 0.80

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


