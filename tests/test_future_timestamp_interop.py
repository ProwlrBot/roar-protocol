#!/usr/bin/env python3
"""Interop matrix: future-timestamp rejection — both SDKs must reject.

Validates the property:
  A message with auth.timestamp set 120 seconds in the future MUST be
  rejected by StrictMessageVerifier in BOTH Python and TypeScript.

This covers the interop-matrix.md row: "Future timestamp | MUST fail"
for all 4 cross-SDK combinations (Python→Python, TS→TS covered by unit
tests; this test adds Python→TS and TS→Python via golden message exchange).
"""

import json
import subprocess
import sys
from pathlib import Path
import time

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.verifier import StrictMessageVerifier


SECRET = "interop-test-secret"
SRC = AgentIdentity(display_name="sender")
DST = AgentIdentity(display_name="receiver")


def make_future_msg() -> ROARMessage:
    msg = ROARMessage(
        **{"from": SRC.model_copy(deep=True), "to": DST.model_copy(deep=True)},
        intent=MessageIntent.DELEGATE,
        payload={"task": "future"},
    )
    msg.sign(SECRET)
    msg.auth["timestamp"] = time.time() + 120  # 2 minutes in the future
    return msg


# --- 1. Python rejects future-timestamped message (own SDK) ---
verifier = StrictMessageVerifier(hmac_secret=SECRET, expected_recipient_did=DST.did)
msg = make_future_msg()
result = verifier.verify(msg)
assert result.error == "message_from_future", (
    f"Python: expected message_from_future, got {result.error!r}"
)
print("Python → Python: future timestamp rejected ✅")


# --- 2. TypeScript rejects a future-timestamped message produced by Python ---
msg2 = make_future_msg()
wire = {
    "id": msg2.id,
    "from": {
        "did": msg2.from_identity.did,
        "display_name": msg2.from_identity.display_name,
        "public_key": msg2.from_identity.public_key,
        "capabilities": list(msg2.from_identity.capabilities),
    },
    "to": {
        "did": msg2.to_identity.did,
        "display_name": msg2.to_identity.display_name,
        "public_key": msg2.to_identity.public_key,
        "capabilities": list(msg2.to_identity.capabilities),
    },
    "intent": msg2.intent,
    "payload": msg2.payload,
    "context": msg2.context,
    "timestamp": msg2.timestamp,
    "auth": dict(msg2.auth),
}

ts_script = f"""
import {{ StrictMessageVerifier }} from './ts/dist/verifier.js';

const msg = {json.dumps(wire, ensure_ascii=False)};
// wire uses "from"/"to"; StrictMessageVerifier accesses msg.to_identity
msg.from_identity = msg.from;
msg.to_identity = msg.to;

const v = new StrictMessageVerifier({{
  hmacSecret: {json.dumps(SECRET)},
  expectedRecipientDid: {json.dumps(DST.did)},
}});
const r = v.verify(msg);
if (r.error !== 'message_from_future') {{
  console.error('FAIL: expected message_from_future, got ' + JSON.stringify(r.error));
  process.exit(1);
}}
console.log('Python → TypeScript: future timestamp rejected ✅');
"""

result = subprocess.run(
    ["node", "--input-type=module"],
    input=ts_script,
    capture_output=True,
    text=True,
    cwd=str(Path(__file__).resolve().parents[1]),
)
if result.returncode != 0:
    print(f"FAIL (TS subprocess): {result.stderr.strip()}")
    sys.exit(1)
print(result.stdout.strip())

print("Future-timestamp interop checks passed.")
