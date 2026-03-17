package roar

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
)

// ROARHub is an agent discovery directory.
type ROARHub struct {
	Host string
	Port int

	mu        sync.RWMutex
	directory map[string]AgentCard // DID -> AgentCard
}

// HubOption configures a ROARHub.
type HubOption func(*ROARHub)

// WithHubHost sets the listen address for the hub (default "127.0.0.1").
func WithHubHost(host string) HubOption {
	return func(h *ROARHub) {
		h.Host = host
	}
}

// WithHubPort sets the listen port for the hub (default 8090).
func WithHubPort(port int) HubOption {
	return func(h *ROARHub) {
		h.Port = port
	}
}

// NewHub creates a new ROARHub with the given options.
func NewHub(opts ...HubOption) *ROARHub {
	h := &ROARHub{
		Host:      "127.0.0.1",
		Port:      8090,
		directory: make(map[string]AgentCard),
	}

	for _, opt := range opts {
		opt(h)
	}

	return h
}

// Register adds an agent card to the directory.
func (h *ROARHub) Register(card AgentCard) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.directory[card.Identity.DID] = card
}

// Unregister removes an agent from the directory by DID.
func (h *ROARHub) Unregister(did string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.directory, did)
}

// Lookup finds a single agent by DID.
func (h *ROARHub) Lookup(did string) (AgentCard, bool) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	card, ok := h.directory[did]
	return card, ok
}

// Search returns all agents that advertise the given capability.
func (h *ROARHub) Search(capability string) []AgentCard {
	h.mu.RLock()
	defer h.mu.RUnlock()

	var results []AgentCard
	for _, card := range h.directory {
		for _, cap := range card.Identity.Capabilities {
			if cap == capability {
				results = append(results, card)
				break
			}
		}
	}
	return results
}

// ListAll returns all registered agent cards.
func (h *ROARHub) ListAll() []AgentCard {
	h.mu.RLock()
	defer h.mu.RUnlock()

	cards := make([]AgentCard, 0, len(h.directory))
	for _, card := range h.directory {
		cards = append(cards, card)
	}
	return cards
}

// Handler returns the http.Handler for this hub, useful for testing with httptest.
func (h *ROARHub) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/roar/health", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"status":   "ok",
			"protocol": "roar/1.0",
			"type":     "hub",
		})
	})

	mux.HandleFunc("/roar/agents/", func(w http.ResponseWriter, r *http.Request) {
		// Extract DID from path: /roar/agents/{did}
		did := strings.TrimPrefix(r.URL.Path, "/roar/agents/")
		if did == "" {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]any{"error": "missing_did"})
			return
		}

		switch r.Method {
		case http.MethodGet:
			card, ok := h.Lookup(did)
			if !ok {
				w.WriteHeader(http.StatusNotFound)
				json.NewEncoder(w).Encode(map[string]any{"error": "not_found"})
				return
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(card)

		case http.MethodDelete:
			h.Unregister(did)
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{"status": "removed"})

		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	})

	mux.HandleFunc("/roar/agents", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			capability := r.URL.Query().Get("capability")
			var agents []AgentCard
			if capability != "" {
				agents = h.Search(capability)
			} else {
				agents = h.ListAll()
			}
			if agents == nil {
				agents = []AgentCard{}
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{"agents": agents})

		case http.MethodPost:
			limited := io.LimitReader(r.Body, maxBodyBytes+1)
			body, err := io.ReadAll(limited)
			if err != nil {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(map[string]any{"error": "read_error"})
				return
			}
			if len(body) > maxBodyBytes {
				w.WriteHeader(http.StatusRequestEntityTooLarge)
				json.NewEncoder(w).Encode(map[string]any{"error": "request_too_large"})
				return
			}

			var card AgentCard
			if err := json.Unmarshal(body, &card); err != nil {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(map[string]any{"error": "invalid_card"})
				return
			}
			if card.Identity.DID == "" {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(map[string]any{"error": "missing_did"})
				return
			}

			h.Register(card)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			json.NewEncoder(w).Encode(map[string]any{"status": "registered", "did": card.Identity.DID})

		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	})

	return mux
}

// Serve starts the HTTP server and blocks until it returns.
func (h *ROARHub) Serve() error {
	addr := fmt.Sprintf("%s:%d", h.Host, h.Port)
	server := &http.Server{
		Addr:    addr,
		Handler: h.Handler(),
	}
	return server.ListenAndServe()
}
