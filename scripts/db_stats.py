#!/usr/bin/env python3
"""Print database statistics for GitHub Actions summary."""

import sqlite3
import sys
from pathlib import Path


def print_statistics(db_path: Path = None) -> int:
    """Print database statistics to stdout.

    Returns 0 on success, 1 on error.
    """
    if db_path is None:
        db_path = Path(__file__).parent.parent / "data" / "voices.db"

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM voices")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT platform) FROM voices")
        platforms = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT engine) FROM voices")
        engines = cur.fetchone()[0]

        print(f"{total} voices from {platforms} platforms, {engines} engines")
        conn.close()
        return 0

    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(print_statistics())
