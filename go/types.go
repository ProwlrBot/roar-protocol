// Package roar implements the ROAR Protocol SDK for Go.
//
// It provides types, signing, and an HTTP client for agent-to-agent
// communication using the ROAR wire format.
package roar

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// AgentIdentity represents a W3C DID-based agent identity.
type AgentIdentity struct {
	DID          string   `json:"did"`
	DisplayName  string   `json:"display_name"`
	AgentType    string   `json:"agent_type"`
	Capabilities []string `json:"capabilities"`
	Version      string   `json:"version"`
	PublicKey    *string  `json:"public_key"`
}

// MessageIntent describes what the sender wants the receiver to do.
type MessageIntent string

const (
	IntentExecute  MessageIntent = "execute"
	IntentDelegate MessageIntent = "delegate"
	IntentUpdate   MessageIntent = "update"
	IntentAsk      MessageIntent = "ask"
	IntentRespond  MessageIntent = "respond"
	IntentNotify   MessageIntent = "notify"
	IntentDiscover MessageIntent = "discover"
)

// ROARMessage is the unified ROAR message — one format for all agent communication.
//
// Wire format uses "from" and "to" as field names (matching Python/TS SDKs).
type ROARMessage struct {
	ROAR         string         `json:"roar"`
	ID           string         `json:"id"`
	FromIdentity AgentIdentity  `json:"from"`
	ToIdentity   AgentIdentity  `json:"to"`
	Intent       MessageIntent  `json:"intent"`
	Payload      map[string]any `json:"payload"`
	Context      map[string]any `json:"context"`
	Auth         map[string]any `json:"auth"`
	Timestamp    float64        `json:"timestamp"`
}

// StreamEvent is a real-time streaming event published via SSE or WebSocket.
type StreamEvent struct {
	Type      string         `json:"type"`
	Source    string         `json:"source"`
	SessionID string        `json:"session_id"`
	Data      map[string]any `json:"data"`
	Timestamp float64        `json:"timestamp"`
	TraceID   string         `json:"trace_id,omitempty"`
}

// AgentCard is a public capability descriptor — an agent's business card for discovery.
type AgentCard struct {
	Identity    AgentIdentity     `json:"identity"`
	Description string            `json:"description"`
	Skills      []string          `json:"skills"`
	Channels    []string          `json:"channels"`
	Endpoints   map[string]string `json:"endpoints"`
}

// IdentityOption is a functional option for NewIdentity.
type IdentityOption func(*AgentIdentity)

// WithAgentType sets the agent type (default "agent").
func WithAgentType(agentType string) IdentityOption {
	return func(id *AgentIdentity) {
		id.AgentType = agentType
	}
}

// WithCapabilities sets the agent capabilities list.
func WithCapabilities(caps []string) IdentityOption {
	return func(id *AgentIdentity) {
		id.Capabilities = caps
	}
}

// WithVersion sets the agent version (default "1.0").
func WithVersion(version string) IdentityOption {
	return func(id *AgentIdentity) {
		id.Version = version
	}
}

// WithPublicKey sets the agent's public key (hex-encoded).
func WithPublicKey(key string) IdentityOption {
	return func(id *AgentIdentity) {
		id.PublicKey = &key
	}
}

// WithDID sets the DID explicitly instead of auto-generating it.
func WithDID(did string) IdentityOption {
	return func(id *AgentIdentity) {
		id.DID = did
	}
}

// NewIdentity creates an AgentIdentity with an auto-generated DID.
//
// The DID format is: did:roar:<agent_type>:<slug>-<16-char hex>
func NewIdentity(displayName string, opts ...IdentityOption) AgentIdentity {
	id := AgentIdentity{
		DisplayName:  displayName,
		AgentType:    "agent",
		Capabilities: []string{},
		Version:      "1.0",
		PublicKey:     nil,
	}

	for _, opt := range opts {
		opt(&id)
	}

	if id.DID == "" {
		uid := make([]byte, 8)
		_, _ = rand.Read(uid)
		hexUID := hex.EncodeToString(uid)

		slug := strings.ToLower(displayName)
		slug = strings.ReplaceAll(slug, " ", "-")
		if len(slug) > 20 {
			slug = slug[:20]
		}
		if slug == "" {
			slug = "agent"
		}

		id.DID = fmt.Sprintf("did:roar:%s:%s-%s", id.AgentType, slug, hexUID)
	}

	return id
}

// NewMessage creates a new ROARMessage with a generated ID and current timestamp.
func NewMessage(from, to AgentIdentity, intent MessageIntent, payload map[string]any) ROARMessage {
	uid := make([]byte, 5)
	_, _ = rand.Read(uid)
	msgID := "msg_" + hex.EncodeToString(uid)

	if payload == nil {
		payload = map[string]any{}
	}

	return ROARMessage{
		ROAR:         "1.0",
		ID:           msgID,
		FromIdentity: from,
		ToIdentity:   to,
		Intent:       intent,
		Payload:      payload,
		Context:      map[string]any{},
		Auth:         map[string]any{},
		Timestamp:    float64(time.Now().UnixMilli()) / 1000.0,
	}
}

// MarshalJSON implements custom JSON marshaling to ensure Capabilities is
// never null (always []) and matches the Python wire format.
func (id AgentIdentity) MarshalJSON() ([]byte, error) {
	caps := id.Capabilities
	if caps == nil {
		caps = []string{}
	}

	type alias AgentIdentity
	return json.Marshal(&struct {
		alias
		Capabilities []string `json:"capabilities"`
	}{
		alias:        alias(id),
		Capabilities: caps,
	})
}
