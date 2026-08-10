#!/usr/bin/env python3
"""
Project Sentinel - Import Migration Tool

This script scans every Python file inside src/
and automatically converts absolute imports like:

    from ai.detector import ObjectDetector

into

    from src.ai.detector import ObjectDetector

It also fixes:

    import ai.detector

to

    import src.ai.detector

Backups are created before every modification.

Run:

    python tools/fix_imports.py

"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

PACKAGE_NAMES = {
    "ai",
    "app_logging",
    "camera",
    "config",
    "dashboard",
    "database",
    "engine",
    "events",
    "face",
    "investigation",
    "motion",
    "notifications",
    "security",
    "utils",
}

BACKUP_SUFFIX = ".bak"

# ---------------------------------------------------------


class ImportRewriter(ast.NodeTransformer):

    def __init__(self):
        self.changed = False

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")

            if parts[0] in PACKAGE_NAMES and parts[0] != "src":
                alias.name = "src." + alias.name
                self.changed = True

        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):

        if node.module is None:
            return node

        parts = node.module.split(".")

        if parts[0] in PACKAGE_NAMES and parts[0] != "src":
            node.module = "src." + node.module
            self.changed = True

        return node


def process_file(path: Path):

    original = path.read_text(encoding="utf8")

    try:
        tree = ast.parse(original)
    except SyntaxError as e:
        print(f"[SKIP] {path} (Syntax Error)")
        print("      ", e)
        return False

    transformer = ImportRewriter()
    tree = transformer.visit(tree)

    if not transformer.changed:
        return False

    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)

    if not backup.exists():
        shutil.copy2(path, backup)

    new_source = ast.unparse(tree)

    path.write_text(new_source + "\n", encoding="utf8")

    print(f"[FIXED] {path.relative_to(PROJECT_ROOT)}")

    return True


def main():

    print("=" * 60)
    print(" Project Sentinel Import Migration Tool")
    print("=" * 60)

    fixed = 0

    for file in SRC.rglob("*.py"):

        if "__pycache__" in str(file):
            continue

        if process_file(file):
            fixed += 1

    print()
    print("=" * 60)
    print(f"Files Updated : {fixed}")
    print("Backups       : *.bak")
    print("=" * 60)


if __name__ == "__main__":
    main()