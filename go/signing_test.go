package roar

import (
	"strings"
	"testing"
)

// goldenMessage returns a ROARMessage matching the golden fixture.
func goldenMessage() ROARMessage {
	return ROARMessage{
		ROAR: "1.0",
		ID:   "msg_a1b2c3d4e5",
		FromIdentity: AgentIdentity{
			DID:          "did:roar:agent:sender-f5e6d7c8a9b01234",
			DisplayName:  "sender",
			AgentType:    "agent",
			Capabilities: []string{"python"},
			Version:      "1.0",
		},
		ToIdentity: AgentIdentity{
			DID:          "did:roar:agent:receiver-k1l2m3n4o5p6q7r8",
			DisplayName:  "receiver",
			AgentType:    "agent",
			Capabilities: []string{"review"},
			Version:      "1.0",
		},
		Intent:  IntentDelegate,
		Payload: map[string]any{"task": "golden conformance test", "priority": "low"},
		Context: map[string]any{"session_id": "sess_golden"},
		Auth: map[string]any{
			"timestamp": 1710000000.0,
			"signature": "hmac-sha256:aa0eabc393ec10e0f92029cef1d4c9d11dd827299b48da9fc4322c9e2df24873",
		},
		Timestamp: 1710000000.0,
	}
}

const goldenSecret = "roar-conformance-test-secret"
const goldenCanonicalJSON = `{"context": {"session_id": "sess_golden"}, "from": "did:roar:agent:sender-f5e6d7c8a9b01234", "id": "msg_a1b2c3d4e5", "intent": "delegate", "payload": {"priority": "low", "task": "golden conformance test"}, "timestamp": 1710000000.0, "to": "did:roar:agent:receiver-k1l2m3n4o5p6q7r8"}`
const goldenSignature = "hmac-sha256:aa0eabc393ec10e0f92029cef1d4c9d11dd827299b48da9fc4322c9e2df24873"

func TestCanonicalBodyMatchesGoldenFixture(t *testing.T) {
	msg := goldenMessage()
	body := signingBody(msg)
	got := string(body)

	if got != goldenCanonicalJSON {
		t.Errorf("canonical body mismatch\ngot:  %s\nwant: %s", got, goldenCanonicalJSON)
	}
}

func TestSignMessageSetsAuthFields(t *testing.T) {
	from := NewIdentity("Sender")
	to := NewIdentity("Receiver")
	msg := NewMessage(from, to, IntentDelegate, map[string]any{"task": "test"})

	SignMessage(&msg, "test-secret")

	sig, ok := msg.Auth["signature"].(string)
	if !ok || sig == "" {
		t.Fatal("Auth['signature'] should be set after signing")
	}
	if !strings.HasPrefix(sig, "hmac-sha256:") {
		t.Errorf("signature should start with hmac-sha256:, got %s", sig)
	}

	ts, ok := msg.Auth["timestamp"].(float64)
	if !ok || ts <= 0 {
		t.Errorf("Auth['timestamp'] should be a positive float, got %v", msg.Auth["timestamp"])
	}
}

func TestVerifyMessageAcceptsValidSignature(t *testing.T) {
	msg := goldenMessage()
	if !VerifyMessage(msg, goldenSecret) {
		t.Error("VerifyMessage should accept the golden fixture signature")
	}
}

func TestVerifyMessageRejectsTamperedPayload(t *testing.T) {
	msg := goldenMessage()
	msg.Payload["task"] = "tampered"

	if VerifyMessage(msg, goldenSecret) {
		t.Error("VerifyMessage should reject tampered payload")
	}
}

func TestVerifyMessageRejectsWrongSecret(t *testing.T) {
	msg := goldenMessage()
	if VerifyMessage(msg, "wrong-secret") {
		t.Error("VerifyMessage should reject wrong secret")
	}
}

func TestSignThenVerifyRoundTrip(t *testing.T) {
	from := NewIdentity("Alice")
	to := NewIdentity("Bob")
	msg := NewMessage(from, to, IntentExecute, map[string]any{"action": "run"})

	SignMessage(&msg, "my-secret")

	if !VerifyMessage(msg, "my-secret") {
		t.Error("VerifyMessage should accept a freshly signed message")
	}

	if VerifyMessage(msg, "other-secret") {
		t.Error("VerifyMessage should reject a different secret")
	}
}

func TestVerifyMessageRejectsMissingSignature(t *testing.T) {
	msg := goldenMessage()
	delete(msg.Auth, "signature")

	if VerifyMessage(msg, goldenSecret) {
		t.Error("VerifyMessage should reject missing signature")
	}
}

func TestVerifyMessageRejectsBadPrefix(t *testing.T) {
	msg := goldenMessage()
	msg.Auth["signature"] = "sha256:abc123"

	if VerifyMessage(msg, goldenSecret) {
		t.Error("VerifyMessage should reject non-hmac-sha256 prefix")
	}
}
