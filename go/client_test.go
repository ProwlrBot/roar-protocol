package roar

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestNewClientCreatesValidClient(t *testing.T) {
	id := NewIdentity("TestBot")
	client := NewClient(id, "secret-key")

	if client.Identity.DID != id.DID {
		t.Errorf("Identity.DID = %q, want %q", client.Identity.DID, id.DID)
	}
	if client.SigningSecret != "secret-key" {
		t.Errorf("SigningSecret = %q, want %q", client.SigningSecret, "secret-key")
	}
	if client.HTTPClient == nil {
		t.Error("HTTPClient should not be nil")
	}
}

func TestSendMarshalsMessageCorrectly(t *testing.T) {
	var receivedBody map[string]any

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/roar/message" {
			t.Errorf("expected path /roar/message, got %s", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Errorf("expected POST, got %s", r.Method)
		}
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("Content-Type = %q, want application/json", ct)
		}

		if err := json.NewDecoder(r.Body).Decode(&receivedBody); err != nil {
			t.Fatalf("decode body: %v", err)
		}

		// Return a valid ROAR response
		resp := ROARMessage{
			ROAR:   "1.0",
			ID:     "msg_response",
			Intent: IntentRespond,
			FromIdentity: AgentIdentity{
				DID:          "did:roar:agent:server-1234567890abcdef",
				DisplayName:  "server",
				AgentType:    "agent",
				Capabilities: []string{},
				Version:      "1.0",
			},
			ToIdentity: AgentIdentity{
				DID:          "did:roar:agent:client-1234567890abcdef",
				DisplayName:  "client",
				AgentType:    "agent",
				Capabilities: []string{},
				Version:      "1.0",
			},
			Payload:   map[string]any{"status": "ok"},
			Context:   map[string]any{},
			Auth:      map[string]any{},
			Timestamp: 1710000000.0,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	from := NewIdentity("Sender")
	to := NewIdentity("Receiver")
	client := NewClient(from, "test-secret")

	msg := NewMessage(from, to, IntentDelegate, map[string]any{"task": "test"})
	resp, err := client.Send(server.URL, msg)
	if err != nil {
		t.Fatalf("Send failed: %v", err)
	}

	// Verify the sent body uses "from" and "to"
	if _, ok := receivedBody["from"]; !ok {
		t.Error("sent JSON should have 'from' key")
	}
	if _, ok := receivedBody["to"]; !ok {
		t.Error("sent JSON should have 'to' key")
	}

	// Verify the message was signed
	auth, ok := receivedBody["auth"].(map[string]any)
	if !ok {
		t.Fatal("auth should be a map")
	}
	sig, ok := auth["signature"].(string)
	if !ok || sig == "" {
		t.Error("sent message should have a signature")
	}

	// Verify response was parsed
	if resp.ID != "msg_response" {
		t.Errorf("response ID = %q, want msg_response", resp.ID)
	}
	if resp.Payload["status"] != "ok" {
		t.Errorf("response Payload[status] = %v, want ok", resp.Payload["status"])
	}
}

func TestHealthReturnsParsedResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/roar/health" {
			t.Errorf("expected path /roar/health, got %s", r.URL.Path)
		}
		if r.Method != http.MethodGet {
			t.Errorf("expected GET, got %s", r.Method)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"status":  "healthy",
			"version": "0.3.0",
		})
	}))
	defer server.Close()

	id := NewIdentity("HealthChecker")
	client := NewClient(id, "secret")

	health, err := client.Health(server.URL)
	if err != nil {
		t.Fatalf("Health failed: %v", err)
	}

	if health["status"] != "healthy" {
		t.Errorf("status = %v, want healthy", health["status"])
	}
	if health["version"] != "0.3.0" {
		t.Errorf("version = %v, want 0.3.0", health["version"])
	}
}

func TestSendHandlesServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error": "internal"}`))
	}))
	defer server.Close()

	from := NewIdentity("Sender")
	to := NewIdentity("Receiver")
	client := NewClient(from, "secret")

	msg := NewMessage(from, to, IntentExecute, nil)
	_, err := client.Send(server.URL, msg)
	if err == nil {
		t.Error("Send should return error on 500 response")
	}
}

func TestHealthHandlesServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		w.Write([]byte(`{"error": "unavailable"}`))
	}))
	defer server.Close()

	client := NewClient(NewIdentity("Bot"), "secret")
	_, err := client.Health(server.URL)
	if err == nil {
		t.Error("Health should return error on 503 response")
	}
}
