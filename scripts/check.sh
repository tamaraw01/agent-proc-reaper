#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Running agent-proc-reaper test suite"
cd "${CLI_ROOT}"
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v

echo "==> Verifying CLI entry point help"
PYTHONPATH=src python3 -m agent_proc_reaper.cli --help > /dev/null

echo "==> Verifying CLI version"
PYTHONPATH=src python3 -m agent_proc_reaper.cli --version | grep "1.0.0" > /dev/null

echo "==> Verifying doctor subcommand"
PYTHONPATH=src python3 -m agent_proc_reaper.cli doctor > /dev/null

echo "==> Scanning for forbidden patterns (em dashes, hardcoded paths, secret tokens)"
TMP_PROBE="$(mktemp)"
trap 'rm -f "${TMP_PROBE}"' EXIT

python3 -c '
import os, sys, re
from pathlib import Path

root = Path("'${CLI_ROOT}'")
forbidden = [
    (re.compile(r"\u2014"), "Em dash detected"),
    (re.compile(r"/home/[a-zA-Z0-9._-]+"), "Hardcoded user home path detected"),
    (re.compile(r"GUMROAD_ACCESS_TOKEN\s*="), "Token assignment detected"),
]

errors = []
for p in root.rglob("*"):
    if not p.is_file():
        continue
    if any(part in {"__pycache__", ".pytest_cache", ".git"} or part.endswith(".pyc") for part in p.parts):
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for pat, desc in forbidden:
        if pat.search(text):
            errors.append(f"{p}: {desc}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
'

echo "==> All CLI checks and safety scans passed cleanly"
