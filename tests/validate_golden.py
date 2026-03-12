#!/usr/bin/env python3
"""ROAR Protocol — Golden fixture conformance validator.

Validates all golden JSON fixtures against the Python reference implementation.
Run from the repo root: python3 tests/validate_golden.py
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path

GOLDEN = Path(__file__).parent / "conformance" / "golden"

try:
    from prowlrbot.protocols.roar import (
        AgentIdentity,
        ROARMessage,
        StreamEvent,
        MessageIntent,
        StreamEventType,
    )
except ImportError:
    print("ERROR: prowlrbot not installed.")
    print("  Install: pip install -e '.[dev]'  (from the prowlrbot repo)")
    sys.exit(1)

DID_PREFIX = "did:roar:"
errors: list[str] = []
passed = 0


def check(name: str, condition: bool, message: str) -> None:
    global passed
    if condition:
        passed += 1
    else:
        errors.append(f"  ✗ {name}: {message}")


# ─── identity.json ──────────────────────────────────────────────────────────
raw = json.loads((GOLDEN / "identity.json").read_text())
raw_clean = {k: v for k, v in raw.items() if not k.startswith("_")}

identity = AgentIdentity(**raw_clean)

check("identity/parse", True, "")
check("identity/did_prefix", identity.did.startswith(DID_PREFIX), f"DID must start with '{DID_PREFIX}', got '{identity.did}'")
check("identity/did_format", ":agent:" in identity.did, f"Expected agent type in DID, got '{identity.did}'")
check("identity/display_name", identity.display_name == "golden-agent", f"Expected 'golden-agent', got '{identity.display_name}'")
check("identity/agent_type", identity.agent_type == "agent", f"Expected 'agent', got '{identity.agent_type}'")
check("identity/capabilities", "python" in identity.capabilities, "Expected 'python' in capabilities")
check("identity/version", identity.version == "1.0", f"Expected '1.0', got '{identity.version}'")
check("identity/public_key_null", identity.public_key is None, "Expected public_key to be None")

# Round-trip: re-serialize and compare field names
serialized = json.loads(identity.model_dump_json(by_alias=True))
check("identity/roundtrip_did", serialized.get("did") == identity.did, "Round-trip: 'did' field missing or changed")
check("identity/roundtrip_agent_type", serialized.get("agent_type") == "agent", "Round-trip: 'agent_type' field wrong")

print("identity.json  ", "✅" if not any("identity" in e for e in errors) else "❌")


# ─── message.json ───────────────────────────────────────────────────────────
raw_msg = json.loads((GOLDEN / "message.json").read_text())
raw_msg_clean = {k: v for k, v in raw_msg.items() if not k.startswith("_")}

msg = ROARMessage(**raw_msg_clean)

check("message/parse", True, "")
check("message/roar_version", msg.roar == "1.0", f"Expected roar='1.0', got '{msg.roar}'")
check("message/id_format", msg.id.startswith("msg_"), f"ID must start with 'msg_', got '{msg.id}'")
check("message/intent_delegate", msg.intent == MessageIntent.DELEGATE, f"Expected 'delegate', got '{msg.intent}'")
check("message/from_did", msg.from_identity.did.startswith(DID_PREFIX), f"from.did must start with '{DID_PREFIX}'")
check("message/to_did", msg.to_identity.did.startswith(DID_PREFIX), f"to.did must start with '{DID_PREFIX}'")
check("message/payload_task", "task" in msg.payload, "Expected 'task' key in payload")
check("message/context_session", msg.context.get("session_id") == "sess_golden", "Expected session_id='sess_golden' in context")
check("message/auth_signature", msg.auth.get("signature", "").startswith("hmac-sha256:"), "auth.signature must start with 'hmac-sha256:'")
check("message/auth_timestamp", msg.auth.get("timestamp") == 1710000000.0, f"Expected auth.timestamp=1710000000.0")

# Verify HMAC
is_valid = msg.verify("roar-conformance-test-secret", max_age_seconds=0)
check("message/signature_valid", is_valid, "HMAC signature verification failed")

print("message.json   ", "✅" if not any("message" in e for e in errors) else "❌")


# ─── stream-event.json ──────────────────────────────────────────────────────
raw_evt = json.loads((GOLDEN / "stream-event.json").read_text())
raw_evt_clean = {k: v for k, v in raw_evt.items() if not k.startswith("_")}

event = StreamEvent(**raw_evt_clean)

check("stream/parse", True, "")
check("stream/type", event.type == StreamEventType.TASK_UPDATE, f"Expected 'task_update', got '{event.type}'")
check("stream/source_did", event.source.startswith(DID_PREFIX), f"source must be a DID, got '{event.source}'")
check("stream/session_id", event.session_id == "sess_golden", f"Expected 'sess_golden', got '{event.session_id}'")
check("stream/data_task_id", "task_id" in event.data, "Expected 'task_id' in data")
check("stream/data_status", event.data.get("status") == "completed", "Expected status='completed'")
check("stream/timestamp", event.timestamp == 1710000000.0, f"Expected timestamp=1710000000.0")

print("stream-event.json", "✅" if not any("stream" in e for e in errors) else "❌")


# ─── signature.json ─────────────────────────────────────────────────────────
raw_sig = json.loads((GOLDEN / "signature.json").read_text())
inputs = raw_sig["inputs"]
secret = raw_sig["secret"]
expected = raw_sig["expected_signature"]

canonical = json.dumps(inputs, sort_keys=True)
actual_hex = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
actual = f"hmac-sha256:{actual_hex}"

check("signature/canonical", canonical == raw_sig["canonical_json"], "Canonical JSON does not match fixture")
check("signature/hmac", actual == expected, f"HMAC mismatch:\n    expected: {expected}\n    got:      {actual}")

print("signature.json ", "✅" if not any("signature" in e for e in errors) else "❌")


# ─── Summary ────────────────────────────────────────────────────────────────
total = passed + len(errors)
print()
if not errors:
    print(f"All {total} conformance checks passed. ✅")
else:
    print(f"{len(errors)}/{total} checks failed:")
    for e in errors:
        print(e)
    sys.exit(1)
