use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

// ---------------------------------------------------------------------------
// Layer 1: Identity
// ---------------------------------------------------------------------------

/// W3C DID-based agent identity. Every ROAR agent has one.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AgentIdentity {
    pub did: String,
    pub display_name: String,
    pub agent_type: String,
    pub capabilities: Vec<String>,
    pub version: String,
    pub public_key: Option<String>,
}

impl AgentIdentity {
    /// Create a new `AgentIdentity` with an auto-generated DID.
    pub fn new(display_name: &str) -> Self {
        let uid = uuid::Uuid::new_v4()
            .to_string()
            .replace('-', "")
            .chars()
            .take(16)
            .collect::<String>();
        let slug: String = display_name
            .to_lowercase()
            .replace(' ', "-")
            .chars()
            .take(20)
            .collect();
        let slug = if slug.is_empty() {
            "agent".to_string()
        } else {
            slug
        };
        Self {
            did: format!("did:roar:agent:{}-{}", slug, uid),
            display_name: display_name.to_string(),
            agent_type: "agent".to_string(),
            capabilities: Vec::new(),
            version: "1.0".to_string(),
            public_key: None,
        }
    }
}

impl Default for AgentIdentity {
    fn default() -> Self {
        Self::new("agent")
    }
}

// ---------------------------------------------------------------------------
// Layer 4: Exchange
// ---------------------------------------------------------------------------

/// What the sender wants the receiver to do.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MessageIntent {
    Execute,
    Delegate,
    Update,
    Ask,
    Respond,
    Notify,
    Discover,
}

/// Unified ROAR message -- one format for all agent communication.
///
/// Wire format uses "from" and "to" as JSON field names.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ROARMessage {
    #[serde(default = "default_roar_version")]
    pub roar: String,
    pub id: String,
    #[serde(rename = "from")]
    pub from_identity: AgentIdentity,
    #[serde(rename = "to")]
    pub to_identity: AgentIdentity,
    pub intent: MessageIntent,
    pub payload: serde_json::Value,
    pub context: serde_json::Value,
    pub auth: serde_json::Value,
    pub timestamp: f64,
}

fn default_roar_version() -> String {
    "1.0".to_string()
}

fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

impl ROARMessage {
    /// Create a new `ROARMessage` with auto-generated id and current timestamp.
    pub fn new(
        from: AgentIdentity,
        to: AgentIdentity,
        intent: MessageIntent,
        payload: serde_json::Value,
    ) -> Self {
        let uid = uuid::Uuid::new_v4()
            .to_string()
            .replace('-', "")
            .chars()
            .take(10)
            .collect::<String>();
        Self {
            roar: "1.0".to_string(),
            id: format!("msg_{}", uid),
            from_identity: from,
            to_identity: to,
            intent,
            payload,
            context: serde_json::json!({}),
            auth: serde_json::json!({}),
            timestamp: now_epoch(),
        }
    }
}

// ---------------------------------------------------------------------------
// Layer 5: Stream
// ---------------------------------------------------------------------------

/// A real-time streaming event published via SSE or WebSocket.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StreamEvent {
    #[serde(rename = "type")]
    pub type_: String,
    pub source: String,
    pub session_id: String,
    pub data: serde_json::Value,
    pub timestamp: f64,
    pub trace_id: String,
}

// ---------------------------------------------------------------------------
// Layer 1 (cont): AgentCard
// ---------------------------------------------------------------------------

/// Public capability descriptor -- an agent's business card for discovery.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AgentCard {
    pub identity: AgentIdentity,
    pub description: String,
    pub skills: Vec<String>,
    pub channels: Vec<String>,
    pub endpoints: HashMap<String, String>,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_identity_new_generates_valid_did() {
        let id = AgentIdentity::new("Test Agent");
        assert!(id.did.starts_with("did:roar:agent:test-agent-"));
        assert_eq!(id.display_name, "Test Agent");
        assert_eq!(id.agent_type, "agent");
        assert_eq!(id.version, "1.0");
        assert!(id.public_key.is_none());
        // DID suffix should be 16 hex chars
        let suffix = id.did.rsplit('-').next().unwrap();
        assert_eq!(suffix.len(), 16);
        assert!(suffix.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn agent_identity_new_unique_dids() {
        let a = AgentIdentity::new("same");
        let b = AgentIdentity::new("same");
        assert_ne!(a.did, b.did);
    }

    #[test]
    fn roar_message_serialization_uses_from_to() {
        let from = AgentIdentity::new("sender");
        let to = AgentIdentity::new("receiver");
        let msg = ROARMessage::new(
            from.clone(),
            to.clone(),
            MessageIntent::Execute,
            serde_json::json!({"action": "test"}),
        );
        let json_str = serde_json::to_string(&msg).unwrap();
        // Must have "from" and "to" keys, NOT "from_identity"/"to_identity"
        assert!(json_str.contains("\"from\""));
        assert!(json_str.contains("\"to\""));
        assert!(!json_str.contains("from_identity"));
        assert!(!json_str.contains("to_identity"));

        // Round-trip: deserialize back
        let parsed: ROARMessage = serde_json::from_str(&json_str).unwrap();
        assert_eq!(parsed.from_identity.did, from.did);
        assert_eq!(parsed.to_identity.did, to.did);
    }

    #[test]
    fn message_intent_serializes_lowercase() {
        assert_eq!(
            serde_json::to_string(&MessageIntent::Execute).unwrap(),
            "\"execute\""
        );
        assert_eq!(
            serde_json::to_string(&MessageIntent::Delegate).unwrap(),
            "\"delegate\""
        );
        assert_eq!(
            serde_json::to_string(&MessageIntent::Discover).unwrap(),
            "\"discover\""
        );
    }

    #[test]
    fn message_intent_round_trips() {
        for intent in &[
            MessageIntent::Execute,
            MessageIntent::Delegate,
            MessageIntent::Update,
            MessageIntent::Ask,
            MessageIntent::Respond,
            MessageIntent::Notify,
            MessageIntent::Discover,
        ] {
            let s = serde_json::to_string(intent).unwrap();
            let parsed: MessageIntent = serde_json::from_str(&s).unwrap();
            assert_eq!(&parsed, intent);
        }
    }

    #[test]
    fn golden_message_deserialization() {
        let golden = include_str!("../../tests/conformance/golden/message.json");
        let msg: ROARMessage = serde_json::from_str(golden).unwrap();
        assert_eq!(msg.id, "msg_a1b2c3d4e5");
        assert_eq!(msg.from_identity.did, "did:roar:agent:sender-f5e6d7c8a9b01234");
        assert_eq!(msg.to_identity.did, "did:roar:agent:receiver-k1l2m3n4o5p6q7r8");
        assert_eq!(msg.intent, MessageIntent::Delegate);
        assert_eq!(msg.timestamp, 1710000000.0);
    }
}
