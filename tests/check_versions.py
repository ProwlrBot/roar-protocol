#!/usr/bin/env python3
"""CI check: roar_sdk.__spec_version__ must match spec/VERSION.json spec_version."""

import json
import sys
from pathlib import Path

try:
    import roar_sdk
except ImportError:
    print("FAIL: roar_sdk not installed. Run: pip install -e ./python")
    sys.exit(1)

spec = json.loads((Path(__file__).parent.parent / "spec" / "VERSION.json").read_text())
sdk_ver = roar_sdk.__spec_version__
spec_ver = spec["spec_version"]

if sdk_ver != spec_ver:
    print(f"FAIL: roar_sdk.__spec_version__ ({sdk_ver!r}) != spec/VERSION.json ({spec_ver!r})")
    print("Update roar_sdk/__init__.py __spec_version__ to match the spec version.")
    sys.exit(1)

print(f"Version aligned: {sdk_ver!r}")
