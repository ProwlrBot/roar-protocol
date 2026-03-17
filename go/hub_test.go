package roar

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func makeCard(did string, name string, caps []string) AgentCard {
	return AgentCard{
		Identity: AgentIdentity{
			DID:          did,
			DisplayName:  name,
			AgentType:    "agent",
			Capabilities: caps,
			Version:      "1.0",
		},
		Description: name + " agent",
		Skills:      []string{},
		Channels:    []string{"http"},
		Endpoints:   map[string]string{"http": "http://localhost:8089"},
	}
}

func TestRegisterAndLookup(t *testing.T) {
	hub := NewHub()
	card := makeCard("did:roar:agent:bot-1", "Bot1", []string{"search"})

	hub.Register(card)
	found, ok := hub.Lookup("did:roar:agent:bot-1")
	if !ok {
		t.Fatal("expected to find registered agent")
	}
	if found.Identity.DID != "did:roar:agent:bot-1" {
		t.Errorf("DID = %q, want did:roar:agent:bot-1", found.Identity.DID)
	}
}

func TestLookupNotFound(t *testing.T) {
	hub := NewHub()
	_, ok := hub.Lookup("did:roar:agent:nonexistent")
	if ok {
		t.Error("expected not found for unregistered DID")
	}
}

func TestSearchByCapability(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:a", "A", []string{"search", "summarize"}))
	hub.Register(makeCard("did:roar:agent:b", "B", []string{"translate"}))
	hub.Register(makeCard("did:roar:agent:c", "C", []string{"search"}))

	results := hub.Search("search")
	if len(results) != 2 {
		t.Errorf("expected 2 results, got %d", len(results))
	}

	results = hub.Search("translate")
	if len(results) != 1 {
		t.Errorf("expected 1 result, got %d", len(results))
	}

	results = hub.Search("nonexistent")
	if len(results) != 0 {
		t.Errorf("expected 0 results, got %d", len(results))
	}
}

func TestListAll(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:a", "A", nil))
	hub.Register(makeCard("did:roar:agent:b", "B", nil))

	all := hub.ListAll()
	if len(all) != 2 {
		t.Errorf("expected 2 agents, got %d", len(all))
	}
}

func TestUnregister(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:a", "A", nil))
	hub.Register(makeCard("did:roar:agent:b", "B", nil))

	hub.Unregister("did:roar:agent:a")

	_, ok := hub.Lookup("did:roar:agent:a")
	if ok {
		t.Error("agent should have been removed")
	}

	all := hub.ListAll()
	if len(all) != 1 {
		t.Errorf("expected 1 agent after unregister, got %d", len(all))
	}
}

func TestHubHTTPHealthEndpoint(t *testing.T) {
	hub := NewHub()
	ts := httptest.NewServer(hub.Handler())
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
	if body["type"] != "hub" {
		t.Errorf("type = %v, want hub", body["type"])
	}
}

func TestHubHTTPListAgents(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:a", "A", []string{"search"}))

	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/agents")
	if err != nil {
		t.Fatalf("GET /roar/agents failed: %v", err)
	}
	defer resp.Body.Close()

	var body map[string]any
	json.NewDecoder(resp.Body).Decode(&body)
	agents, ok := body["agents"].([]any)
	if !ok || len(agents) != 1 {
		t.Fatalf("expected 1 agent, got %v", body["agents"])
	}
}

func TestHubHTTPListAgentsWithCapabilityFilter(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:a", "A", []string{"search"}))
	hub.Register(makeCard("did:roar:agent:b", "B", []string{"translate"}))

	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/agents?capability=search")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	defer resp.Body.Close()

	var body map[string]any
	json.NewDecoder(resp.Body).Decode(&body)
	agents := body["agents"].([]any)
	if len(agents) != 1 {
		t.Errorf("expected 1 agent with search capability, got %d", len(agents))
	}
}

func TestHubHTTPRegisterAgent(t *testing.T) {
	hub := NewHub()
	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	card := makeCard("did:roar:agent:new", "NewBot", []string{"code"})
	body, _ := json.Marshal(card)

	resp, err := http.Post(ts.URL+"/roar/agents", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST /roar/agents failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 201 {
		t.Errorf("status = %d, want 201", resp.StatusCode)
	}

	// Verify it's in the directory
	found, ok := hub.Lookup("did:roar:agent:new")
	if !ok {
		t.Error("registered agent should be in directory")
	}
	if found.Identity.DisplayName != "NewBot" {
		t.Errorf("display name = %q, want NewBot", found.Identity.DisplayName)
	}
}

func TestHubHTTPLookupAgent(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:lookup-test", "LookupBot", nil))

	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/agents/did:roar:agent:lookup-test")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}

	var card AgentCard
	json.NewDecoder(resp.Body).Decode(&card)
	if card.Identity.DID != "did:roar:agent:lookup-test" {
		t.Errorf("DID = %q, want did:roar:agent:lookup-test", card.Identity.DID)
	}
}

func TestHubHTTPLookupNotFound(t *testing.T) {
	hub := NewHub()
	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/agents/did:roar:agent:nope")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 404 {
		t.Errorf("status = %d, want 404", resp.StatusCode)
	}
}

func TestHubHTTPDeleteAgent(t *testing.T) {
	hub := NewHub()
	hub.Register(makeCard("did:roar:agent:del", "DelBot", nil))

	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	req, _ := http.NewRequest(http.MethodDelete, ts.URL+"/roar/agents/did:roar:agent:del", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("DELETE failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}

	// Verify it's gone
	_, ok := hub.Lookup("did:roar:agent:del")
	if ok {
		t.Error("agent should have been removed")
	}
}

func TestHubHTTPEmptyListReturnsEmptyArray(t *testing.T) {
	hub := NewHub()
	ts := httptest.NewServer(hub.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/roar/agents")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	defer resp.Body.Close()

	var body map[string]any
	json.NewDecoder(resp.Body).Decode(&body)
	agents, ok := body["agents"].([]any)
	if !ok {
		t.Fatal("agents should be an array")
	}
	if len(agents) != 0 {
		t.Errorf("expected 0 agents, got %d", len(agents))
	}
}
