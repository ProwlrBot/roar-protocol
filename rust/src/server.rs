use std::collections::{HashMap, HashSet, VecDeque};
use std::io::Read;

use crate::signing::verify_message;
use crate::types::{AgentCard, AgentIdentity, MessageIntent, ROARMessage};

/// Maximum number of remembered message IDs for replay protection.
const MAX_SEEN: usize = 10_000;

/// Maximum request body size: 1 MiB.
const MAX_BODY: usize = 1_048_576;

type Handler = Box<dyn Fn(&ROARMessage) -> ROARMessage + Send + Sync>;

/// A lightweight ROAR protocol server.
///
/// Registers per-intent handlers and serves them over HTTP using `tiny_http`.
pub struct ROARServer {
    pub identity: AgentIdentity,
    signing_secret: Option<String>,
    host: String,
    port: u16,
    handlers: HashMap<MessageIntent, Handler>,
    seen_ids: HashSet<String>,
    seen_order: VecDeque<String>,
    description: String,
}

impl ROARServer {
    /// Create a new server for the given agent identity.
    pub fn new(identity: AgentIdentity) -> Self {
        Self {
            description: format!("ROAR agent: {}", identity.display_name),
            identity,
            signing_secret: None,
            host: "127.0.0.1".to_string(),
            port: 9000,
            handlers: HashMap::new(),
            seen_ids: HashSet::new(),
            seen_order: VecDeque::new(),
        }
    }

    /// Set the HMAC signing secret (builder pattern).
    pub fn with_signing_secret(mut self, secret: &str) -> Self {
        self.signing_secret = Some(secret.to_string());
        self
    }

    /// Set the listen host (builder pattern).
    pub fn with_host(mut self, host: &str) -> Self {
        self.host = host.to_string();
        self
    }

    /// Set the listen port (builder pattern).
    pub fn with_port(mut self, port: u16) -> Self {
        self.port = port;
        self
    }

    /// Set the description for the agent card (builder pattern).
    pub fn with_description(mut self, desc: &str) -> Self {
        self.description = desc.to_string();
        self
    }

    /// Register a handler for a specific message intent.
    pub fn on(
        &mut self,
        intent: MessageIntent,
        handler: impl Fn(&ROARMessage) -> ROARMessage + Send + Sync + 'static,
    ) {
        self.handlers.insert(intent, Box::new(handler));
    }

    /// Process an incoming message: verify, check replay, dispatch.
    pub fn handle_message(&mut self, msg: &ROARMessage) -> Result<ROARMessage, String> {
        // Verify signature if a secret is configured
        if let Some(ref secret) = self.signing_secret {
            if !verify_message(msg, secret) {
                return Err("signature verification failed".to_string());
            }
        }

        // Replay protection
        if self.seen_ids.contains(&msg.id) {
            return Err(format!("duplicate message id: {}", msg.id));
        }
        self.seen_order.push_back(msg.id.clone());
        self.seen_ids.insert(msg.id.clone());
        while self.seen_ids.len() > MAX_SEEN {
            if let Some(old) = self.seen_order.pop_front() {
                self.seen_ids.remove(&old);
            }
        }

        // Dispatch to registered handler
        match self.handlers.get(&msg.intent) {
            Some(handler) => Ok(handler(msg)),
            None => Err(format!(
                "no handler registered for intent: {:?}",
                msg.intent
            )),
        }
    }

    /// Build the public `AgentCard` for this server.
    pub fn get_card(&self) -> AgentCard {
        let mut endpoints = HashMap::new();
        let base = format!("http://{}:{}", self.host, self.port);
        endpoints.insert("message".to_string(), format!("{}/roar/message", base));
        endpoints.insert("agents".to_string(), format!("{}/roar/agents", base));
        endpoints.insert("health".to_string(), format!("{}/roar/health", base));

        AgentCard {
            identity: self.identity.clone(),
            description: self.description.clone(),
            skills: self.identity.capabilities.clone(),
            channels: vec!["http".to_string()],
            endpoints,
        }
    }

    /// Start the HTTP server (blocks the calling thread).
    pub fn serve(&mut self) -> Result<(), String> {
        let addr = format!("{}:{}", self.host, self.port);
        let server = tiny_http::Server::http(&addr)
            .map_err(|e| format!("failed to bind {}: {}", addr, e))?;

        eprintln!("ROAR server listening on {}", addr);

        for mut request in server.incoming_requests() {
            let (status, body) = self.route(&mut request);
            let response = tiny_http::Response::from_string(body)
                .with_status_code(status)
                .with_header(
                    tiny_http::Header::from_bytes(
                        &b"Content-Type"[..],
                        &b"application/json"[..],
                    )
                    .unwrap(),
                );
            let _ = request.respond(response);
        }

        Ok(())
    }

    /// Route a single HTTP request and return (status_code, response_body).
    fn route(&mut self, request: &mut tiny_http::Request) -> (u16, String) {
        let method = request.method().to_string();
        let url = request.url().to_string();

        match (method.as_str(), url.as_str()) {
            ("GET", "/roar/health") => {
                (200, r#"{"status": "ok"}"#.to_string())
            }
            ("GET", "/roar/agents") => match serde_json::to_string(&self.get_card()) {
                Ok(json) => (200, json),
                Err(e) => (500, format!(r#"{{"error": "{}"}}"#, e)),
            },
            ("POST", "/roar/message") => {
                // Read body with size limit
                let content_length = request
                    .body_length()
                    .unwrap_or(0);
                if content_length > MAX_BODY {
                    return (
                        413,
                        r#"{"error": "request body too large"}"#.to_string(),
                    );
                }

                let mut body = Vec::new();
                let reader = request.as_reader();
                match reader.take(MAX_BODY as u64).read_to_end(&mut body) {
                    Ok(_) => {}
                    Err(e) => {
                        return (
                            400,
                            format!(r#"{{"error": "failed to read body: {}"}}"#, e),
                        );
                    }
                }

                let msg: ROARMessage = match serde_json::from_slice(&body) {
                    Ok(m) => m,
                    Err(e) => {
                        return (
                            400,
                            format!(r#"{{"error": "invalid JSON: {}"}}"#, e),
                        );
                    }
                };

                match self.handle_message(&msg) {
                    Ok(resp) => match serde_json::to_string(&resp) {
                        Ok(json) => (200, json),
                        Err(e) => (500, format!(r#"{{"error": "{}"}}"#, e)),
                    },
                    Err(e) => (400, format!(r#"{{"error": "{}"}}"#, e)),
                }
            }
            _ => (404, r#"{"error": "not found"}"#.to_string()),
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::signing::sign_message;
    use crate::types::{AgentIdentity, MessageIntent, ROARMessage};

    fn make_identity(name: &str) -> AgentIdentity {
        AgentIdentity {
            did: format!("did:roar:agent:{}", name),
            display_name: name.to_string(),
            agent_type: "agent".to_string(),
            capabilities: vec!["test".to_string()],
            version: "1.0".to_string(),
            public_key: None,
        }
    }

    fn make_message(intent: MessageIntent) -> ROARMessage {
        ROARMessage::new(
            make_identity("alice"),
            make_identity("bob"),
            intent,
            serde_json::json!({"action": "test"}),
        )
    }

    #[test]
    fn test_on_and_handle_message_dispatch() {
        let identity = make_identity("server");
        let mut server = ROARServer::new(identity);

        server.on(MessageIntent::Execute, |msg| {
            ROARMessage::new(
                msg.to_identity.clone(),
                msg.from_identity.clone(),
                MessageIntent::Respond,
                serde_json::json!({"result": "done"}),
            )
        });

        let msg = make_message(MessageIntent::Execute);
        let resp = server.handle_message(&msg).unwrap();
        assert_eq!(resp.intent, MessageIntent::Respond);
        assert_eq!(resp.payload["result"], "done");
    }

    #[test]
    fn test_signature_verification_pass() {
        let identity = make_identity("server");
        let secret = "test-secret";
        let mut server = ROARServer::new(identity).with_signing_secret(secret);

        server.on(MessageIntent::Execute, |msg| {
            ROARMessage::new(
                msg.to_identity.clone(),
                msg.from_identity.clone(),
                MessageIntent::Respond,
                serde_json::json!({"ok": true}),
            )
        });

        let mut msg = make_message(MessageIntent::Execute);
        sign_message(&mut msg, secret);

        let resp = server.handle_message(&msg);
        assert!(resp.is_ok());
    }

    #[test]
    fn test_signature_verification_fail() {
        let identity = make_identity("server");
        let mut server = ROARServer::new(identity).with_signing_secret("correct-secret");

        server.on(MessageIntent::Execute, |_msg| {
            ROARMessage::new(
                make_identity("a"),
                make_identity("b"),
                MessageIntent::Respond,
                serde_json::json!({}),
            )
        });

        let mut msg = make_message(MessageIntent::Execute);
        sign_message(&mut msg, "wrong-secret");

        let resp = server.handle_message(&msg);
        assert!(resp.is_err());
        assert!(resp.unwrap_err().contains("signature verification failed"));
    }

    #[test]
    fn test_replay_rejection() {
        let identity = make_identity("server");
        let mut server = ROARServer::new(identity);

        server.on(MessageIntent::Execute, |msg| {
            ROARMessage::new(
                msg.to_identity.clone(),
                msg.from_identity.clone(),
                MessageIntent::Respond,
                serde_json::json!({}),
            )
        });

        let msg = make_message(MessageIntent::Execute);

        // First time should succeed
        let resp1 = server.handle_message(&msg);
        assert!(resp1.is_ok());

        // Second time with same ID should fail
        let resp2 = server.handle_message(&msg);
        assert!(resp2.is_err());
        assert!(resp2.unwrap_err().contains("duplicate message id"));
    }

    #[test]
    fn test_unhandled_intent_error() {
        let identity = make_identity("server");
        let mut server = ROARServer::new(identity);

        // Register only Execute handler
        server.on(MessageIntent::Execute, |msg| {
            ROARMessage::new(
                msg.to_identity.clone(),
                msg.from_identity.clone(),
                MessageIntent::Respond,
                serde_json::json!({}),
            )
        });

        // Send a Notify message — no handler registered for it
        let msg = make_message(MessageIntent::Notify);
        let resp = server.handle_message(&msg);
        assert!(resp.is_err());
        assert!(resp.unwrap_err().contains("no handler registered"));
    }

    #[test]
    fn test_get_card() {
        let mut identity = make_identity("card-test");
        identity.capabilities = vec!["code".to_string(), "review".to_string()];

        let server = ROARServer::new(identity)
            .with_host("0.0.0.0")
            .with_port(8080)
            .with_description("My test agent");

        let card = server.get_card();
        assert_eq!(card.identity.did, "did:roar:agent:card-test");
        assert_eq!(card.description, "My test agent");
        assert_eq!(card.skills, vec!["code", "review"]);
        assert_eq!(card.channels, vec!["http"]);
        assert!(card.endpoints["message"].contains("8080"));
        assert!(card.endpoints["message"].contains("/roar/message"));
    }

    #[test]
    fn test_builder_pattern_chaining() {
        let identity = make_identity("builder");
        let server = ROARServer::new(identity)
            .with_host("localhost")
            .with_port(3000)
            .with_signing_secret("s3cret")
            .with_description("builder test");

        assert_eq!(server.host, "localhost");
        assert_eq!(server.port, 3000);
        assert_eq!(server.signing_secret, Some("s3cret".to_string()));
        assert_eq!(server.description, "builder test");
    }

    #[test]
    fn test_replay_eviction() {
        let identity = make_identity("eviction");
        let mut server = ROARServer::new(identity);

        server.on(MessageIntent::Execute, |msg| {
            ROARMessage::new(
                msg.to_identity.clone(),
                msg.from_identity.clone(),
                MessageIntent::Respond,
                serde_json::json!({}),
            )
        });

        // Fill the seen set beyond MAX_SEEN
        for i in 0..=MAX_SEEN {
            let mut msg = make_message(MessageIntent::Execute);
            msg.id = format!("msg_{}", i);
            let _ = server.handle_message(&msg);
        }

        // The oldest ID should have been evicted
        assert!(!server.seen_ids.contains("msg_0"));
        // The newest should still be present
        assert!(server.seen_ids.contains(&format!("msg_{}", MAX_SEEN)));
        assert!(server.seen_ids.len() <= MAX_SEEN);
    }
}
