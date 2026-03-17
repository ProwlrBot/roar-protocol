package roar

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
)

// HandlerFunc is a function that handles a ROAR message and returns a response.
type HandlerFunc func(msg ROARMessage) (ROARMessage, error)

// ROARServer receives and dispatches ROAR messages to intent handlers.
type ROARServer struct {
	Identity      AgentIdentity
	SigningSecret string
	Host          string
	Port          int

	handlers    map[string]HandlerFunc
	description string
	skills      []string
	channels    []string

	mu           sync.Mutex
	seenMessages map[string]bool // replay protection
	seenOrder    []string        // FIFO eviction order
}

// maxSeenMessages is the upper bound on tracked message IDs for replay protection.
const maxSeenMessages = 10_000

// maxBodyBytes is the maximum request body size (1 MiB).
const maxBodyBytes = 1 * 1024 * 1024

// ServerOption configures a ROARServer.
type ServerOption func(*ROARServer)

// WithSigningSecret sets the HMAC signing secret for signature verification.
func WithSigningSecret(secret string) ServerOption {
	return func(s *ROARServer) {
		s.SigningSecret = secret
	}
}

// WithHost sets the listen address (default "127.0.0.1").
func WithHost(host string) ServerOption {
	return func(s *ROARServer) {
		s.Host = host
	}
}

// WithPort sets the listen port (default 8089).
func WithPort(port int) ServerOption {
	return func(s *ROARServer) {
		s.Port = port
	}
}

// WithDescription sets the server description for the agent card.
func WithDescription(desc string) ServerOption {
	return func(s *ROARServer) {
		s.description = desc
	}
}

// WithSkills sets the skills advertised in the agent card.
func WithSkills(skills []string) ServerOption {
	return func(s *ROARServer) {
		s.skills = skills
	}
}

// WithChannels sets the channels advertised in the agent card.
func WithChannels(channels []string) ServerOption {
	return func(s *ROARServer) {
		s.channels = channels
	}
}

// NewServer creates a new ROARServer with the given identity and options.
func NewServer(identity AgentIdentity, opts ...ServerOption) *ROARServer {
	s := &ROARServer{
		Identity:     identity,
		Host:         "127.0.0.1",
		Port:         8089,
		handlers:     make(map[string]HandlerFunc),
		skills:       []string{},
		channels:     []string{},
		seenMessages: make(map[string]bool),
		seenOrder:    make([]string, 0),
	}

	for _, opt := range opts {
		opt(s)
	}

	return s
}

// On registers a handler for the given message intent. Returns the server for chaining.
func (s *ROARServer) On(intent MessageIntent, handler HandlerFunc) *ROARServer {
	s.handlers[string(intent)] = handler
	return s
}

// HandleMessage dispatches an incoming message to the registered handler.
// It performs replay protection and signature verification when configured.
func (s *ROARServer) HandleMessage(msg ROARMessage) (ROARMessage, error) {
	// Replay protection
	s.mu.Lock()
	if s.seenMessages[msg.ID] {
		s.mu.Unlock()
		return ROARMessage{}, fmt.Errorf("roar: replay detected for message %s", msg.ID)
	}
	s.seenMessages[msg.ID] = true
	s.seenOrder = append(s.seenOrder, msg.ID)
	// Evict oldest entries if we exceed the bound
	for len(s.seenOrder) > maxSeenMessages {
		oldest := s.seenOrder[0]
		s.seenOrder = s.seenOrder[1:]
		delete(s.seenMessages, oldest)
	}
	s.mu.Unlock()

	// Signature verification
	if s.SigningSecret != "" {
		if !VerifyMessage(msg, s.SigningSecret) {
			return ROARMessage{}, fmt.Errorf("roar: signature verification failed")
		}
	}

	handler, ok := s.handlers[string(msg.Intent)]
	if !ok {
		return NewMessage(s.Identity, msg.FromIdentity, IntentRespond, map[string]any{
			"error":   "unhandled_intent",
			"message": fmt.Sprintf("No handler registered for intent '%s'", msg.Intent),
		}), nil
	}

	return handler(msg)
}

// GetCard builds and returns this server's AgentCard.
func (s *ROARServer) GetCard() AgentCard {
	return AgentCard{
		Identity:    s.Identity,
		Description: s.description,
		Skills:      s.skills,
		Channels:    s.channels,
		Endpoints: map[string]string{
			"http": fmt.Sprintf("http://%s:%d", s.Host, s.Port),
		},
	}
}

// Handler returns the http.Handler for this server, useful for testing with httptest.
func (s *ROARServer) Handler() http.Handler {
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
		})
	})

	mux.HandleFunc("/roar/agents", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"agents": []AgentCard{s.GetCard()},
		})
	})

	mux.HandleFunc("/roar/message", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		// Bounded body read
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

		var msg ROARMessage
		if err := json.Unmarshal(body, &msg); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]any{
				"error":  "invalid_message",
				"detail": "Request body is not a valid ROAR message.",
			})
			return
		}

		resp, err := s.HandleMessage(msg)
		if err != nil {
			// Signature failure or replay
			w.WriteHeader(http.StatusUnauthorized)
			json.NewEncoder(w).Encode(map[string]any{
				"error":   "message_rejected",
				"message": err.Error(),
			})
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	})

	return mux
}

// Serve starts the HTTP server and blocks until it returns.
func (s *ROARServer) Serve() error {
	addr := fmt.Sprintf("%s:%d", s.Host, s.Port)
	server := &http.Server{
		Addr:    addr,
		Handler: s.Handler(),
	}
	return server.ListenAndServe()
}
