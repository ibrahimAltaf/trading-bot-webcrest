"""
Run once to create DB tables. From backend root:

  python scripts/init_db.py

Or:

  PYTHONPATH=. python scripts/init_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root (parent of `src/`) is on sys.path when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db.base import Base
from src.db.session import engine
import src.db.models  # noqa: F401  — registers models


def main():
    Base.metadata.create_all(bind=engine)
    print("✅ DB tables created successfully")


if __name__ == "__main__":
    main()
