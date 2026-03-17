package roar

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestNewIdentityGeneratesValidDID(t *testing.T) {
	id := NewIdentity("Test Agent")

	if !strings.HasPrefix(id.DID, "did:roar:agent:test-agent-") {
		t.Errorf("DID should start with did:roar:agent:test-agent-, got %s", id.DID)
	}

	// DID should have a 16-char hex suffix
	parts := strings.Split(id.DID, "-")
	hexPart := parts[len(parts)-1]
	if len(hexPart) != 16 {
		t.Errorf("DID hex suffix should be 16 chars, got %d: %s", len(hexPart), hexPart)
	}

	if id.DisplayName != "Test Agent" {
		t.Errorf("DisplayName = %q, want %q", id.DisplayName, "Test Agent")
	}
	if id.AgentType != "agent" {
		t.Errorf("AgentType = %q, want %q", id.AgentType, "agent")
	}
	if id.Version != "1.0" {
		t.Errorf("Version = %q, want %q", id.Version, "1.0")
	}
	if id.PublicKey != nil {
		t.Errorf("PublicKey should be nil, got %v", id.PublicKey)
	}
}

func TestNewIdentityWithOptions(t *testing.T) {
	id := NewIdentity("My Tool",
		WithAgentType("tool"),
		WithCapabilities([]string{"python", "review"}),
		WithVersion("2.0"),
	)

	if !strings.HasPrefix(id.DID, "did:roar:tool:my-tool-") {
		t.Errorf("DID should start with did:roar:tool:my-tool-, got %s", id.DID)
	}
	if id.AgentType != "tool" {
		t.Errorf("AgentType = %q, want %q", id.AgentType, "tool")
	}
	if len(id.Capabilities) != 2 || id.Capabilities[0] != "python" {
		t.Errorf("Capabilities = %v, want [python review]", id.Capabilities)
	}
	if id.Version != "2.0" {
		t.Errorf("Version = %q, want %q", id.Version, "2.0")
	}
}

func TestNewIdentityWithExplicitDID(t *testing.T) {
	id := NewIdentity("Agent", WithDID("did:roar:agent:custom-1234567890abcdef"))
	if id.DID != "did:roar:agent:custom-1234567890abcdef" {
		t.Errorf("DID = %q, want explicit value", id.DID)
	}
}

func TestNewMessageCreatesCorrectStructure(t *testing.T) {
	from := NewIdentity("Sender")
	to := NewIdentity("Receiver")
	payload := map[string]any{"task": "test"}

	msg := NewMessage(from, to, IntentDelegate, payload)

	if !strings.HasPrefix(msg.ID, "msg_") {
		t.Errorf("ID should start with msg_, got %s", msg.ID)
	}
	if msg.ROAR != "1.0" {
		t.Errorf("ROAR = %q, want %q", msg.ROAR, "1.0")
	}
	if msg.Intent != IntentDelegate {
		t.Errorf("Intent = %q, want %q", msg.Intent, IntentDelegate)
	}
	if msg.FromIdentity.DID != from.DID {
		t.Errorf("FromIdentity.DID = %q, want %q", msg.FromIdentity.DID, from.DID)
	}
	if msg.ToIdentity.DID != to.DID {
		t.Errorf("ToIdentity.DID = %q, want %q", msg.ToIdentity.DID, to.DID)
	}
	if msg.Payload["task"] != "test" {
		t.Errorf("Payload[task] = %v, want test", msg.Payload["task"])
	}
	if msg.Timestamp <= 0 {
		t.Errorf("Timestamp should be positive, got %f", msg.Timestamp)
	}
}

func TestNewMessageNilPayload(t *testing.T) {
	from := NewIdentity("A")
	to := NewIdentity("B")
	msg := NewMessage(from, to, IntentNotify, nil)

	if msg.Payload == nil {
		t.Error("Payload should be empty map, not nil")
	}
}

func TestJSONMarshalUsesFromAndTo(t *testing.T) {
	from := NewIdentity("Sender", WithDID("did:roar:agent:sender-f5e6d7c8a9b01234"))
	to := NewIdentity("Receiver", WithDID("did:roar:agent:receiver-k1l2m3n4o5p6q7r8"))

	msg := ROARMessage{
		ROAR:         "1.0",
		ID:           "msg_a1b2c3d4e5",
		FromIdentity: from,
		ToIdentity:   to,
		Intent:       IntentDelegate,
		Payload:      map[string]any{"task": "test"},
		Context:      map[string]any{},
		Auth:         map[string]any{},
		Timestamp:    1710000000.0,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}

	// Should use "from" and "to", not "from_identity" / "to_identity"
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatalf("Unmarshal failed: %v", err)
	}

	if _, ok := raw["from"]; !ok {
		t.Error("JSON should have 'from' key, not 'from_identity'")
	}
	if _, ok := raw["to"]; !ok {
		t.Error("JSON should have 'to' key, not 'to_identity'")
	}
	if _, ok := raw["from_identity"]; ok {
		t.Error("JSON should NOT have 'from_identity' key")
	}
	if _, ok := raw["to_identity"]; ok {
		t.Error("JSON should NOT have 'to_identity' key")
	}
}

func TestJSONUnmarshalFromWireFormat(t *testing.T) {
	// Simulate the golden message wire format
	wire := `{
		"roar": "1.0",
		"id": "msg_a1b2c3d4e5",
		"from": {
			"did": "did:roar:agent:sender-f5e6d7c8a9b01234",
			"display_name": "sender",
			"agent_type": "agent",
			"capabilities": ["python"],
			"version": "1.0",
			"public_key": null
		},
		"to": {
			"did": "did:roar:agent:receiver-k1l2m3n4o5p6q7r8",
			"display_name": "receiver",
			"agent_type": "agent",
			"capabilities": ["review"],
			"version": "1.0",
			"public_key": null
		},
		"intent": "delegate",
		"payload": {"task": "golden conformance test", "priority": "low"},
		"context": {"session_id": "sess_golden"},
		"auth": {
			"signature": "hmac-sha256:aa0eabc393ec10e0f92029cef1d4c9d11dd827299b48da9fc4322c9e2df24873",
			"timestamp": 1710000000.0
		},
		"timestamp": 1710000000.0
	}`

	var msg ROARMessage
	if err := json.Unmarshal([]byte(wire), &msg); err != nil {
		t.Fatalf("Unmarshal failed: %v", err)
	}

	if msg.FromIdentity.DID != "did:roar:agent:sender-f5e6d7c8a9b01234" {
		t.Errorf("FromIdentity.DID = %q", msg.FromIdentity.DID)
	}
	if msg.ToIdentity.DID != "did:roar:agent:receiver-k1l2m3n4o5p6q7r8" {
		t.Errorf("ToIdentity.DID = %q", msg.ToIdentity.DID)
	}
	if msg.Intent != IntentDelegate {
		t.Errorf("Intent = %q, want delegate", msg.Intent)
	}
	if msg.Payload["task"] != "golden conformance test" {
		t.Errorf("Payload[task] = %v", msg.Payload["task"])
	}
}

func TestAgentIdentityCapabilitiesNeverNull(t *testing.T) {
	id := AgentIdentity{
		DID:         "did:roar:agent:test-1234567890abcdef",
		DisplayName: "test",
		AgentType:   "agent",
		Version:     "1.0",
		// Capabilities is nil
	}

	data, err := json.Marshal(id)
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}

	// Should serialize as [] not null
	if strings.Contains(string(data), `"capabilities":null`) {
		t.Error("capabilities should be [] not null in JSON")
	}
}
