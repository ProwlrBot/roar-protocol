#!/usr/bin/env python3
"""CI check: verify signature.json canonical body and HMAC value are stable.

Fails if someone changes inputs without recomputing the expected signature,
or if Python's json.dumps sort order changes.
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path

GOLDEN = Path(__file__).parent / "conformance" / "golden" / "signature.json"
data = json.loads(GOLDEN.read_text())

canonical = json.dumps(data["inputs"], sort_keys=True)
if canonical != data["canonical_json"]:
    print("FAIL: canonical JSON has changed")
    print("  expected:", data["canonical_json"])
    print("  got:     ", canonical)
    sys.exit(1)

actual = "hmac-sha256:" + hmac.new(
    data["secret"].encode(),
    canonical.encode(),
    hashlib.sha256,
).hexdigest()

if actual != data["expected_signature"]:
    print("FAIL: HMAC value has changed")
    print("  expected:", data["expected_signature"])
    print("  got:     ", actual)
    sys.exit(1)

print("signature.json stable:", actual[:52] + "...")
