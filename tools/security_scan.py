#!/usr/bin/env python3
"""Project Sentinel static security scan (no network, no dependencies).

Usage: python tools/security_scan.py [path ...] [--staged]
Exit code 1 when any HIGH finding exists. Suppress a reviewed line with the comment:  # sentinel-ok
Findings never print the secret itself (only a masked excerpt)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# .agents/.freebuff are local agent tooling, not application code; vendored skills there
# contain deliberate placeholder examples (e.g. GEMINI_API_KEY="...") that would drown
# out real findings.
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache",
             ".ruff_cache", "snapshots", "data", ".agents", ".freebuff", "sentinel.egg-info",
             "build", "dist",
             # Tests contain deliberate fake credentials and attack payloads; docs contain
             # placeholder URLs. Both are still scanned by --staged (the pre-commit path)
             # and by gitleaks over the full history in CI.
             "tests", "docs"}
SKIP_SUFFIX = {".pt", ".onnx", ".jpg", ".jpeg", ".png", ".db", ".zip", ".pyc", ".bak"}
# Secrets are configured in .env by design (and it is git-ignored), so a normal scan of
# the working tree must not report it. --staged scans it explicitly: if a .env was
# force-added, it will still be flagged before it reaches a commit.
SKIP_ENV_FILES = {".env"}
SELF = Path(__file__).resolve()

# (id, severity, regex, message, applies_to_suffixes or None)
RULES = [
    ("SEC001", "HIGH", r"\d{6,12}:[A-Za-z0-9_-]{30,}", "Telegram bot token", None),
    ("SEC002", "HIGH", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----", "Private key", None),
    ("SEC003", "HIGH", r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id", None),
    ("SEC004", "HIGH", r"://[^/\s:@'\"<>*]+:(?!\*\*\*|PASS\b|pass\b|password\b|<)[^/\s@'\"<>]{3,}@[\w.-]+",
     "Credentials embedded in a URL", None),
    ("SEC005", "HIGH", r"(?i)\b[\w-]*(?:password|passwd|secret|api[_-]?key|token)[\w-]*\s*=\s*[\"'](?!https?://)[^\"'\s]{8,}[\"']",
     "Hardcoded secret assignment", {".py"}),
    ("SEC010", "HIGH", r"\bpickle\.loads?\(|\bpickle\.load\(", "pickle deserialisation (code execution risk)", {".py"}),
    ("SEC011", "HIGH", r"\bdebug\s*=\s*True\b", "Debug mode enabled", {".py"}),
    ("SEC012", "HIGH", r"host\s*=\s*[\"']0\.0\.0\.0[\"']", "Binds to all interfaces", {".py"}),
    ("SEC013", "HIGH", r"\bshell\s*=\s*True\b", "subprocess with shell=True", {".py"}),
    ("SEC014", "HIGH", r"(?<![\w.])(?:eval|exec)\(", "eval/exec", {".py"}),
    ("SEC015", "HIGH", r"verify\s*=\s*False", "TLS verification disabled", {".py"}),
    ("SEC016", "MEDIUM", r"\byaml\.load\((?![^)]*Loader\s*=\s*yaml\.SafeLoader)", "yaml.load without SafeLoader", {".py"}),
    ("SEC017", "HIGH", r"(?i)execute\(\s*f[\"']|execute\([^)]*[\"']\s*%\s|execute\([^)]*[\"']\s*\+", "SQL built from strings", {".py"}),
    ("SEC020", "HIGH", r"\|\s*safe\b|render_template_string|\bMarkup\(", "XSS: autoescape bypass", {".py", ".html"}),
    ("SEC021", "MEDIUM", r"\.innerHTML\s*=|document\.write\(", "XSS sink in JavaScript", {".js", ".html"}),
    ("SEC022", "MEDIUM", r"<script(?![^>]*\bsrc=)[^>]*>", "Inline <script> (blocked by CSP)", {".html"}),
    ("SEC023", "HIGH", r"Access-Control-Allow-Origin|CORS\(", "CORS enabled (app is same-origin only)", {".py"}),
    ("SEC030", "MEDIUM", r"\b(?:print)\(.*(?:token|password|secret)", "print() of a secret-like value", {".py"}),
]
COMPILED = [(i, s, re.compile(p), m, suf) for i, s, p, m, suf in RULES]


def mask(line: str) -> str:
    line = line.strip()
    line = re.sub(r"\d{6,12}:[A-Za-z0-9_-]{30,}", "<TOKEN-REDACTED>", line)
    line = re.sub(r"(://[^/\s:@]+:)[^/\s@]+(@)", r"\1***\2", line)
    line = re.sub(r"([\"'])[^\"']{8,}\1", r"\1***\1", line)
    return line[:140]


def iter_files(paths: list[Path], skip_env: bool = True):
    for base in paths:
        if base.is_file():
            if skip_env and base.name in SKIP_ENV_FILES:
                continue
            yield base
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix in SKIP_SUFFIX:
                continue
            if set(f.relative_to(base).parts[:-1]) & SKIP_DIRS:
                continue
            if skip_env and (f.name in SKIP_ENV_FILES or f.name.startswith(".env.")):
                continue
            yield f


def scan_file(path: Path):
    if path.resolve() == SELF:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    for n, line in enumerate(text.splitlines(), 1):
        if "sentinel-ok" in line:
            continue
        for rid, sev, rx, msg, suffixes in COMPILED:
            if suffixes and path.suffix not in suffixes:
                continue
            if rx.search(line):
                yield rid, sev, n, msg, mask(line)


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                             capture_output=True, text=True, cwd=ROOT, check=False).stdout.split()
        targets = [ROOT / f for f in out if (ROOT / f).suffix not in SKIP_SUFFIX]
    else:
        targets = [Path(a).resolve() for a in args] or [ROOT]
    high = 0
    for f in iter_files(targets, skip_env=not staged):
        for rid, sev, n, msg, excerpt in scan_file(f):
            try:
                shown = f.relative_to(ROOT)
            except ValueError:
                shown = f
            print(f"[{sev}] {rid} {shown}:{n}  {msg}\n        {excerpt}")
            high += sev == "HIGH"
    print(f"\n{high} HIGH finding(s)." if high else "\nNo HIGH findings.")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
