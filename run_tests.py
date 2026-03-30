#!/usr/bin/env python
"""Find all SQLite databases with actual tables"""
import os
import sqlite3

search_dirs = [
    os.path.expanduser("~"),
    r"C:\Users\delap\Documents\Code\GitHub",
]

found = []
for search_dir in search_dirs:
    for root, dirs, files in os.walk(search_dir):
        # Skip venv and .git directories for speed
        dirs[:] = [d for d in dirs if d not in ("venv", ".git", "__pycache__", "node_modules")]
        for f in files:
            if f.endswith(".db"):
                path = os.path.join(root, f)
                try:
                    size = os.path.getsize(path)
                    if size > 100000:  # Only files > 100KB
                        conn = sqlite3.connect(path)
                        rows = conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                        conn.close()
                        if rows:
                            found.append((path, size, [r[0] for r in rows]))
                            print(f"FOUND: {path} ({size/1024/1024:.1f}MB)")
                            print(f"  Tables: {[r[0] for r in rows]}")
                except Exception as e:
                    pass

if not found:
    print("No databases with tables found.")
