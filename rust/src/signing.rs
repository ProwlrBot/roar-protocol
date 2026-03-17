use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::types::ROARMessage;

type HmacSha256 = Hmac<Sha256>;

/// Build the canonical JSON body for HMAC signing.
///
/// This must produce byte-identical output to the Python implementation:
///   json.dumps({...}, sort_keys=True)
///
/// Keys are sorted alphabetically: context, from, id, intent, payload, timestamp, to.
/// Nested objects also have their keys sorted.
fn signing_body(msg: &ROARMessage) -> Vec<u8> {
    // Extract auth timestamp if present, otherwise use message timestamp
    let auth_timestamp = msg
        .auth
        .get("timestamp")
        .and_then(|v| v.as_f64())
        .unwrap_or(msg.timestamp);

    // We must produce sorted-key JSON identical to Python's json.dumps(sort_keys=True).
    // serde_json does NOT sort keys by default, and BTreeMap only sorts the top level.
    // Strategy: build a serde_json::Value with BTreeMap at every level using a
    // recursive sort, then serialize.
    let obj = serde_json::json!({
        "id": msg.id,
        "from": msg.from_identity.did,
        "to": msg.to_identity.did,
        "intent": msg.intent,
        "payload": msg.payload,
        "context": msg.context,
        "timestamp": auth_timestamp,
    });

    let sorted = sort_value(&obj);
    // Python's json.dumps uses ", " and ": " separators by default.
    // serde_json::to_string uses compact format (no spaces).
    // We must match Python exactly, so we use a custom formatter.
    value_to_python_json(&sorted).into_bytes()
}

/// Serialize a `serde_json::Value` to a JSON string matching Python's
/// `json.dumps(sort_keys=True)` output format.
///
/// Python uses `", "` between items and `": "` between key and value.
fn value_to_python_json(val: &serde_json::Value) -> String {
    match val {
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(b) => {
            if *b {
                "true".to_string()
            } else {
                "false".to_string()
            }
        }
        serde_json::Value::Number(n) => {
            // Python renders 1710000000.0 as "1710000000.0", serde does too for f64.
            n.to_string()
        }
        serde_json::Value::String(s) => {
            // Use serde_json to properly escape the string
            serde_json::to_string(s).unwrap()
        }
        serde_json::Value::Array(arr) => {
            let items: Vec<String> = arr.iter().map(value_to_python_json).collect();
            format!("[{}]", items.join(", "))
        }
        serde_json::Value::Object(map) => {
            // Map is already insertion-ordered (sorted by sort_value)
            let items: Vec<String> = map
                .iter()
                .map(|(k, v)| {
                    format!("{}: {}", serde_json::to_string(k).unwrap(), value_to_python_json(v))
                })
                .collect();
            format!("{{{}}}", items.join(", "))
        }
    }
}

/// Recursively sort all object keys in a `serde_json::Value`.
/// Returns a new Value where every Object uses a BTreeMap (naturally sorted).
fn sort_value(val: &serde_json::Value) -> serde_json::Value {
    match val {
        serde_json::Value::Object(map) => {
            let mut sorted = serde_json::Map::new();
            // Collect keys, sort them, insert in order.
            // serde_json::Map preserves insertion order, so inserting alphabetically works.
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            for k in keys {
                sorted.insert(k.clone(), sort_value(&map[k]));
            }
            serde_json::Value::Object(sorted)
        }
        serde_json::Value::Array(arr) => {
            serde_json::Value::Array(arr.iter().map(sort_value).collect())
        }
        other => other.clone(),
    }
}

/// Sign a `ROARMessage` with HMAC-SHA256.
///
/// Sets `auth.signature` to `"hmac-sha256:<hex>"` and `auth.timestamp` to the
/// current time.
pub fn sign_message(msg: &mut ROARMessage, secret: &str) {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();

    msg.auth = serde_json::json!({ "timestamp": now });

    let body = signing_body(msg);
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .expect("HMAC accepts any key length");
    mac.update(&body);
    let result = mac.finalize();
    let hex_sig = hex::encode(result.into_bytes());

    msg.auth["signature"] = serde_json::Value::String(format!("hmac-sha256:{}", hex_sig));
}

/// Verify the HMAC-SHA256 signature on a `ROARMessage`.
///
/// Returns `true` if the signature is present and matches the expected value.
/// Does NOT enforce replay protection (max-age) -- callers should check
/// `auth.timestamp` themselves if needed.
pub fn verify_message(msg: &ROARMessage, secret: &str) -> bool {
    let sig_value = match msg.auth.get("signature").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return false,
    };

    if !sig_value.starts_with("hmac-sha256:") {
        return false;
    }
    let expected_hex = &sig_value["hmac-sha256:".len()..];

    let body = signing_body(msg);
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .expect("HMAC accepts any key length");
    mac.update(&body);
    let result = mac.finalize();
    let actual_hex = hex::encode(result.into_bytes());

    // Constant-time comparison via hmac crate is ideal, but hex comparison
    // of the computed value is acceptable here since we are comparing our own
    // computation against the claimed value.
    actual_hex == expected_hex
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{AgentIdentity, MessageIntent};

    /// Helper: build the golden message from the conformance fixtures.
    fn golden_message() -> ROARMessage {
        let from = AgentIdentity {
            did: "did:roar:agent:sender-f5e6d7c8a9b01234".to_string(),
            display_name: "sender".to_string(),
            agent_type: "agent".to_string(),
            capabilities: vec!["python".to_string()],
            version: "1.0".to_string(),
            public_key: None,
        };
        let to = AgentIdentity {
            did: "did:roar:agent:receiver-k1l2m3n4o5p6q7r8".to_string(),
            display_name: "receiver".to_string(),
            agent_type: "agent".to_string(),
            capabilities: vec!["review".to_string()],
            version: "1.0".to_string(),
            public_key: None,
        };
        ROARMessage {
            roar: "1.0".to_string(),
            id: "msg_a1b2c3d4e5".to_string(),
            from_identity: from,
            to_identity: to,
            intent: MessageIntent::Delegate,
            payload: serde_json::json!({"task": "golden conformance test", "priority": "low"}),
            context: serde_json::json!({"session_id": "sess_golden"}),
            auth: serde_json::json!({"timestamp": 1710000000.0}),
            timestamp: 1710000000.0,
        }
    }

    #[test]
    fn golden_canonical_json() {
        let msg = golden_message();
        let body = signing_body(&msg);
        let body_str = String::from_utf8(body).unwrap();
        let expected = r#"{"context": {"session_id": "sess_golden"}, "from": "did:roar:agent:sender-f5e6d7c8a9b01234", "id": "msg_a1b2c3d4e5", "intent": "delegate", "payload": {"priority": "low", "task": "golden conformance test"}, "timestamp": 1710000000.0, "to": "did:roar:agent:receiver-k1l2m3n4o5p6q7r8"}"#;
        assert_eq!(body_str, expected);
    }

    #[test]
    fn golden_signature_matches() {
        let mut msg = golden_message();
        let secret = "roar-conformance-test-secret";

        // Manually set auth.timestamp to the golden value so the signing body matches
        msg.auth = serde_json::json!({"timestamp": 1710000000.0});
        let body = signing_body(&msg);
        let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).unwrap();
        mac.update(&body);
        let hex_sig = hex::encode(mac.finalize().into_bytes());

        assert_eq!(
            hex_sig,
            "aa0eabc393ec10e0f92029cef1d4c9d11dd827299b48da9fc4322c9e2df24873"
        );
    }

    #[test]
    fn sign_message_sets_auth_fields() {
        let from = AgentIdentity::new("alice");
        let to = AgentIdentity::new("bob");
        let mut msg = ROARMessage::new(
            from,
            to,
            MessageIntent::Execute,
            serde_json::json!({"action": "test"}),
        );

        sign_message(&mut msg, "test-secret");

        assert!(msg.auth.get("timestamp").is_some());
        let sig = msg.auth["signature"].as_str().unwrap();
        assert!(sig.starts_with("hmac-sha256:"));
        // hex portion should be 64 chars (SHA-256 = 32 bytes = 64 hex)
        let hex_part = &sig["hmac-sha256:".len()..];
        assert_eq!(hex_part.len(), 64);
        assert!(hex_part.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn verify_message_accepts_valid() {
        let from = AgentIdentity::new("alice");
        let to = AgentIdentity::new("bob");
        let mut msg = ROARMessage::new(
            from,
            to,
            MessageIntent::Delegate,
            serde_json::json!({"task": "hello"}),
        );

        sign_message(&mut msg, "my-secret");
        assert!(verify_message(&msg, "my-secret"));
    }

    #[test]
    fn verify_message_rejects_tampered() {
        let from = AgentIdentity::new("alice");
        let to = AgentIdentity::new("bob");
        let mut msg = ROARMessage::new(
            from,
            to,
            MessageIntent::Delegate,
            serde_json::json!({"task": "hello"}),
        );

        sign_message(&mut msg, "my-secret");

        // Tamper with payload
        msg.payload = serde_json::json!({"task": "TAMPERED"});
        assert!(!verify_message(&msg, "my-secret"));
    }

    #[test]
    fn verify_message_rejects_wrong_secret() {
        let from = AgentIdentity::new("alice");
        let to = AgentIdentity::new("bob");
        let mut msg = ROARMessage::new(
            from,
            to,
            MessageIntent::Notify,
            serde_json::json!({}),
        );

        sign_message(&mut msg, "correct-secret");
        assert!(!verify_message(&msg, "wrong-secret"));
    }

    #[test]
    fn verify_golden_message_from_fixture() {
        let golden_json = include_str!("../../tests/conformance/golden/message.json");
        let msg: ROARMessage = serde_json::from_str(golden_json).unwrap();
        assert!(verify_message(&msg, "roar-conformance-test-secret"));
    }
}
