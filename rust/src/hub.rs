use std::collections::HashMap;

use crate::types::AgentCard;

/// A ROAR agent discovery hub.
///
/// Maintains a directory of registered agent cards and serves them over HTTP.
pub struct ROARHub {
    host: String,
    port: u16,
    directory: HashMap<String, AgentCard>,
}

impl ROARHub {
    /// Create a new hub with default settings.
    pub fn new() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 9100,
            directory: HashMap::new(),
        }
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

    /// Register an agent card in the directory.
    pub fn register(&mut self, card: AgentCard) {
        self.directory
            .insert(card.identity.did.clone(), card);
    }

    /// Remove an agent from the directory. Returns true if it was present.
    pub fn unregister(&mut self, did: &str) -> bool {
        self.directory.remove(did).is_some()
    }

    /// Look up an agent card by DID.
    pub fn lookup(&self, did: &str) -> Option<&AgentCard> {
        self.directory.get(did)
    }

    /// Search for agents that advertise a given capability/skill.
    pub fn search(&self, capability: &str) -> Vec<&AgentCard> {
        self.directory
            .values()
            .filter(|card| {
                card.skills.iter().any(|s| s == capability)
                    || card.identity.capabilities.iter().any(|c| c == capability)
            })
            .collect()
    }

    /// List all registered agent cards.
    pub fn list_all(&self) -> Vec<&AgentCard> {
        self.directory.values().collect()
    }

    /// Start the HTTP server (blocks the calling thread).
    pub fn serve(&self) -> Result<(), String> {
        let addr = format!("{}:{}", self.host, self.port);
        let server = tiny_http::Server::http(&addr)
            .map_err(|e| format!("failed to bind {}: {}", addr, e))?;

        eprintln!("ROAR hub listening on {}", addr);

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
    fn route(&self, request: &mut tiny_http::Request) -> (u16, String) {
        let method = request.method().to_string();
        let url = request.url().to_string();

        match (method.as_str(), url.as_str()) {
            ("GET", "/roar/health") => {
                (200, r#"{"status": "ok"}"#.to_string())
            }
            ("GET", "/roar/agents") => {
                let cards: Vec<&AgentCard> = self.directory.values().collect();
                match serde_json::to_string(&cards) {
                    Ok(json) => (200, json),
                    Err(e) => (500, format!(r#"{{"error": "{}"}}"#, e)),
                }
            }
            ("POST", "/roar/agents") => {
                // Registration requires reading the body — but hub is &self,
                // so we return instructions. In practice the hub would use
                // interior mutability; for now we return 405.
                (
                    405,
                    r#"{"error": "runtime registration not supported; use hub.register() in code"}"#
                        .to_string(),
                )
            }
            _ if url.starts_with("/roar/agents/") && method == "GET" => {
                let did_suffix = &url["/roar/agents/".len()..];
                // URL-decode the DID (colons may be encoded as %3A)
                let did = did_suffix.replace("%3A", ":");
                match self.directory.get(&did) {
                    Some(card) => match serde_json::to_string(card) {
                        Ok(json) => (200, json),
                        Err(e) => (500, format!(r#"{{"error": "{}"}}"#, e)),
                    },
                    None => (404, r#"{"error": "agent not found"}"#.to_string()),
                }
            }
            _ if url.starts_with("/roar/search?capability=") && method == "GET" => {
                let capability = &url["/roar/search?capability=".len()..];
                let results = self.search(capability);
                match serde_json::to_string(&results) {
                    Ok(json) => (200, json),
                    Err(e) => (500, format!(r#"{{"error": "{}"}}"#, e)),
                }
            }
            _ => (404, r#"{"error": "not found"}"#.to_string()),
        }
    }
}

impl Default for ROARHub {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::AgentIdentity;
    use std::collections::HashMap;

    fn make_card(name: &str, skills: Vec<&str>) -> AgentCard {
        AgentCard {
            identity: AgentIdentity {
                did: format!("did:roar:agent:{}", name),
                display_name: name.to_string(),
                agent_type: "agent".to_string(),
                capabilities: skills.iter().map(|s| s.to_string()).collect(),
                version: "1.0".to_string(),
                public_key: None,
            },
            description: format!("{} agent", name),
            skills: skills.iter().map(|s| s.to_string()).collect(),
            channels: vec!["http".to_string()],
            endpoints: HashMap::new(),
        }
    }

    #[test]
    fn test_register_and_lookup() {
        let mut hub = ROARHub::new();
        let card = make_card("alice", vec!["code"]);
        hub.register(card);

        let found = hub.lookup("did:roar:agent:alice");
        assert!(found.is_some());
        assert_eq!(found.unwrap().identity.display_name, "alice");

        // Non-existent DID
        assert!(hub.lookup("did:roar:agent:nobody").is_none());
    }

    #[test]
    fn test_search_by_capability() {
        let mut hub = ROARHub::new();
        hub.register(make_card("alice", vec!["code", "review"]));
        hub.register(make_card("bob", vec!["review"]));
        hub.register(make_card("carol", vec!["deploy"]));

        let reviewers = hub.search("review");
        assert_eq!(reviewers.len(), 2);
        let names: Vec<&str> = reviewers
            .iter()
            .map(|c| c.identity.display_name.as_str())
            .collect();
        assert!(names.contains(&"alice"));
        assert!(names.contains(&"bob"));

        // No match
        let none = hub.search("nonexistent");
        assert!(none.is_empty());
    }

    #[test]
    fn test_list_all() {
        let mut hub = ROARHub::new();
        assert!(hub.list_all().is_empty());

        hub.register(make_card("alice", vec!["code"]));
        hub.register(make_card("bob", vec!["review"]));
        hub.register(make_card("carol", vec!["deploy"]));

        assert_eq!(hub.list_all().len(), 3);
    }

    #[test]
    fn test_unregister() {
        let mut hub = ROARHub::new();
        hub.register(make_card("alice", vec!["code"]));
        hub.register(make_card("bob", vec!["review"]));

        assert_eq!(hub.list_all().len(), 2);

        let removed = hub.unregister("did:roar:agent:alice");
        assert!(removed);
        assert_eq!(hub.list_all().len(), 1);
        assert!(hub.lookup("did:roar:agent:alice").is_none());

        // Removing non-existent returns false
        let removed_again = hub.unregister("did:roar:agent:alice");
        assert!(!removed_again);
    }

    #[test]
    fn test_register_overwrites_same_did() {
        let mut hub = ROARHub::new();
        hub.register(make_card("alice", vec!["code"]));
        hub.register(make_card("alice", vec!["code", "review"]));

        assert_eq!(hub.list_all().len(), 1);
        let card = hub.lookup("did:roar:agent:alice").unwrap();
        assert_eq!(card.skills.len(), 2);
    }

    #[test]
    fn test_builder_pattern() {
        let hub = ROARHub::new()
            .with_host("0.0.0.0")
            .with_port(5555);

        assert_eq!(hub.host, "0.0.0.0");
        assert_eq!(hub.port, 5555);
    }

    #[test]
    fn test_default() {
        let hub = ROARHub::default();
        assert_eq!(hub.host, "127.0.0.1");
        assert_eq!(hub.port, 9100);
        assert!(hub.directory.is_empty());
    }
}
