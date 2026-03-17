package roar

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOnRegistersHandler(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id)

	called := false
	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		called = true
		return NewMessage(id, msg.FromIdentity, IntentRespond, map[string]any{"ok": true}), nil
	})

	from := NewIdentity("Sender")
	msg := NewMessage(from, id, IntentExecute, map[string]any{"task": "test"})
	_, err := s.HandleMessage(msg)
	if err != nil {
		t.Fatalf("HandleMessage failed: %v", err)
	}
	if !called {
		t.Error("handler was not called")
	}
}

func TestHandleMessageDispatchesToCorrectHandler(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id)

	var executeCalled, askCalled bool
	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		executeCalled = true
		return NewMessage(id, msg.FromIdentity, IntentRespond, nil), nil
	})
	s.On(IntentAsk, func(msg ROARMessage) (ROARMessage, error) {
		askCalled = true
		return NewMessage(id, msg.FromIdentity, IntentRespond, nil), nil
	})

	from := NewIdentity("Sender")

	// Send an ask message
	msg := NewMessage(from, id, IntentAsk, nil)
	_, err := s.HandleMessage(msg)
	if err != nil {
		t.Fatalf("HandleMessage failed: %v", err)
	}
	if !askCalled {
		t.Error("ask handler was not called")
	}
	if executeCalled {
		t.Error("execute handler should not have been called")
	}
}

func TestHandleMessageVerifiesSignatureWhenSecretSet(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id, WithSigningSecret("my-secret"))

	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		return NewMessage(id, msg.FromIdentity, IntentRespond, nil), nil
	})

	from := NewIdentity("Sender")
	msg := NewMessage(from, id, IntentExecute, nil)

	// Message is not signed — should fail verification
	_, err := s.HandleMessage(msg)
	if err == nil {
		t.Error("expected error for unsigned message when secret is set")
	}

	// Now sign the message properly
	msg2 := NewMessage(from, id, IntentExecute, nil)
	SignMessage(&msg2, "my-secret")
	resp, err := s.HandleMessage(msg2)
	if err != nil {
		t.Fatalf("HandleMessage failed for signed message: %v", err)
	}
	if resp.Intent != IntentRespond {
		t.Errorf("response intent = %q, want %q", resp.Intent, IntentRespond)
	}
}

func TestHandleMessageRejectsReplay(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id)

	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		return NewMessage(id, msg.FromIdentity, IntentRespond, nil), nil
	})

	from := NewIdentity("Sender")
	msg := NewMessage(from, id, IntentExecute, nil)

	// First call should succeed
	_, err := s.HandleMessage(msg)
	if err != nil {
		t.Fatalf("first HandleMessage failed: %v", err)
	}

	// Second call with same ID should be rejected
	_, err = s.HandleMessage(msg)
	if err == nil {
		t.Error("expected replay rejection for duplicate message ID")
	}
}

func TestHandleMessageReturnsErrorForUnhandledIntent(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id)

	// No handlers registered
	from := NewIdentity("Sender")
	msg := NewMessage(from, id, IntentExecute, nil)

	resp, err := s.HandleMessage(msg)
	if err != nil {
		t.Fatalf("HandleMessage should not return error for unhandled intent, got: %v", err)
	}

	if resp.Payload["error"] != "unhandled_intent" {
		t.Errorf("expected unhandled_intent error, got: %v", resp.Payload)
	}
}

func TestGetCardReturnsCorrectCard(t *testing.T) {
	id := NewIdentity("CardBot",
		WithCapabilities([]string{"search", "summarize"}),
	)
	s := NewServer(id,
		WithDescription("A test bot"),
		WithHost("0.0.0.0"),
		WithPort(9000),
		WithSkills([]string{"search"}),
		WithChannels([]string{"http"}),
	)

	card := s.GetCard()
	if card.Identity.DID != id.DID {
		t.Errorf("card DID = %q, want %q", card.Identity.DID, id.DID)
	}
	if card.Description != "A test bot" {
		t.Errorf("description = %q, want %q", card.Description, "A test bot")
	}
	if card.Endpoints["http"] != "http://0.0.0.0:9000" {
		t.Errorf("endpoint = %q, want http://0.0.0.0:9000", card.Endpoints["http"])
	}
	if len(card.Skills) != 1 || card.Skills[0] != "search" {
		t.Errorf("skills = %v, want [search]", card.Skills)
	}
	if len(card.Channels) != 1 || card.Channels[0] != "http" {
		t.Errorf("channels = %v, want [http]", card.Channels)
	}
}

func TestServeHTTPHealth(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id)

	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/health")
	if err != nil {
		t.Fatalf("GET /roar/health failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}

	var body map[string]any
	json.NewDecoder(resp.Body).Decode(&body)
	if body["status"] != "ok" {
		t.Errorf("health status = %v, want ok", body["status"])
	}
	if body["protocol"] != "roar/1.0" {
		t.Errorf("protocol = %v, want roar/1.0", body["protocol"])
	}
}

func TestServeHTTPAgents(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id, WithDescription("test"))

	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/agents")
	if err != nil {
		t.Fatalf("GET /roar/agents failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}

	var body map[string]any
	json.NewDecoder(resp.Body).Decode(&body)
	agents, ok := body["agents"].([]any)
	if !ok || len(agents) != 1 {
		t.Fatalf("expected 1 agent, got %v", body["agents"])
	}
}

func TestServeHTTPMessageEndpoint(t *testing.T) {
	serverID := NewIdentity("TestServer")
	s := NewServer(serverID)

	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		return NewMessage(serverID, msg.FromIdentity, IntentRespond, map[string]any{
			"result": "done",
		}), nil
	})

	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	from := NewIdentity("Client")
	msg := NewMessage(from, serverID, IntentExecute, map[string]any{"task": "test"})

	body, _ := json.Marshal(msg)
	resp, err := http.Post(ts.URL+"/roar/message", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST /roar/message failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}

	var result ROARMessage
	json.NewDecoder(resp.Body).Decode(&result)
	if result.Payload["result"] != "done" {
		t.Errorf("payload result = %v, want done", result.Payload["result"])
	}
}

func TestServeHTTPMessageRejectsUnsigned(t *testing.T) {
	serverID := NewIdentity("TestServer")
	s := NewServer(serverID, WithSigningSecret("server-secret"))

	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		return NewMessage(serverID, msg.FromIdentity, IntentRespond, nil), nil
	})

	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	from := NewIdentity("Client")
	msg := NewMessage(from, serverID, IntentExecute, nil)

	// Send without signing
	body, _ := json.Marshal(msg)
	resp, err := http.Post(ts.URL+"/roar/message", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 401 {
		t.Errorf("status = %d, want 401", resp.StatusCode)
	}
}

func TestServeHTTPMessageRejectsReplay(t *testing.T) {
	serverID := NewIdentity("TestServer")
	s := NewServer(serverID)

	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		return NewMessage(serverID, msg.FromIdentity, IntentRespond, nil), nil
	})

	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	from := NewIdentity("Client")
	msg := NewMessage(from, serverID, IntentExecute, nil)

	body, _ := json.Marshal(msg)

	// First request should succeed
	resp1, _ := http.Post(ts.URL+"/roar/message", "application/json", bytes.NewReader(body))
	resp1.Body.Close()
	if resp1.StatusCode != 200 {
		t.Errorf("first request status = %d, want 200", resp1.StatusCode)
	}

	// Second request with same body should be rejected (replay)
	resp2, _ := http.Post(ts.URL+"/roar/message", "application/json", bytes.NewReader(body))
	resp2.Body.Close()
	if resp2.StatusCode != 401 {
		t.Errorf("replay request status = %d, want 401", resp2.StatusCode)
	}
}

func TestSeenMessagesEviction(t *testing.T) {
	id := NewIdentity("TestServer")
	s := NewServer(id)

	s.On(IntentExecute, func(msg ROARMessage) (ROARMessage, error) {
		return NewMessage(id, msg.FromIdentity, IntentRespond, nil), nil
	})

	from := NewIdentity("Sender")

	// Fill up beyond the max
	for i := 0; i < maxSeenMessages+100; i++ {
		msg := NewMessage(from, id, IntentExecute, nil)
		_, _ = s.HandleMessage(msg)
	}

	// The map should not exceed the max
	s.mu.Lock()
	count := len(s.seenMessages)
	s.mu.Unlock()

	if count > maxSeenMessages {
		t.Errorf("seenMessages count = %d, should be <= %d", count, maxSeenMessages)
	}
}
