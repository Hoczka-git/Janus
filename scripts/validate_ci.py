#!/usr/bin/env python3
"""Validate `.github/workflows/ci.yml` with a no-dependency, structure-only check.

Checks:
1. No tabs (YAML best practice — GitHub Actions docs recommend spaces).
2. Indentation is multiples of 2.
3. Required top-level keys are present.
4. The verification step references `pytest`.
5. File ends cleanly (no stray backslash).
"""
from pathlib import Path

path = Path(".github/workflows/ci.yml")
text = path.read_text(encoding="utf-8")

errors = []

if "\t" in text:
    errors.append("contains tabs (GitHub Actions YAML should use spaces)")

for lineno, line in enumerate(text.splitlines(), 1):
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent % 2 != 0 and stripped:
        errors.append(f"line {lineno}: indentation not a multiple of 2 ({indent} spaces)")

for key in ("name:", "on:", "jobs:"):
    if key not in text:
        errors.append(f"missing top-level key '{key}'")

if "pytest" not in text:
    errors.append("no step references pytest")

if text.rstrip().endswith("\\"):
    errors.append("file ends with a stray backslash")

if errors:
    for e in errors:
        print(f"ERROR: ci.yml — {e}")
    raise SystemExit(1)

print(f"ci.yml: OK (keys, indentation, pytest step, no tabs, no stray trailing backslash)")
print(f"  path={path}")
