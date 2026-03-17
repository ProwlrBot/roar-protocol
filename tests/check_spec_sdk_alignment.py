#!/usr/bin/env python3
"""CI check: verify spec version and SDK versions are aligned."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def main() -> int:
    errors: list[str] = []

    # Read spec version
    version_file = ROOT / "spec" / "VERSION.json"
    with open(version_file) as f:
        spec = json.load(f)
    spec_ver = spec["spec_version"]
    py_min = spec["compatibility"]["python_sdk_min_version"]
    ts_min = spec["compatibility"]["ts_sdk_min_version"]

    # Read Python SDK version from pyproject.toml
    pyproject = ROOT / "python" / "pyproject.toml"
    py_ver = None
    for line in pyproject.read_text().splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            py_ver = m.group(1)
            break
    if not py_ver:
        errors.append("Could not find version in python/pyproject.toml")
    elif parse_version(py_ver) < parse_version(py_min):
        errors.append(
            f"Python SDK {py_ver} < required minimum {py_min} for spec {spec_ver}"
        )

    # Read TypeScript SDK version from package.json
    ts_pkg = ROOT / "ts" / "package.json"
    with open(ts_pkg) as f:
        ts_data = json.load(f)
    ts_ver = ts_data.get("version", "")
    if parse_version(ts_ver) < parse_version(ts_min):
        errors.append(
            f"TypeScript SDK {ts_ver} < required minimum {ts_min} for spec {spec_ver}"
        )

    # Report
    print(f"Spec version:      {spec_ver}")
    print(f"Python SDK:        {py_ver} (min: {py_min})")
    print(f"TypeScript SDK:    {ts_ver} (min: {ts_min})")

    if errors:
        print("\nALIGNMENT ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\nAll versions aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
