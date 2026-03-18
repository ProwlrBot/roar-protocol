package roar

import (
	"crypto/rand"
	"encoding/hex"
	"sync"
	"time"
)

// StreamEventType constants matching the ROAR spec Layer 5 event types.
const (
	EventToolCall     = "tool_call"
	EventMCPRequest   = "mcp_request"
	EventReasoning    = "reasoning"
	EventTaskUpdate   = "task_update"
	EventMonitorAlert = "monitor_alert"
	EventAgentStatus  = "agent_status"
	EventCheckpoint   = "checkpoint"
	EventWorldUpdate  = "world_update"
)

// StreamFilter filters events by type, source DID, or session ID.
// All non-empty criteria are combined with AND logic.
type StreamFilter struct {
	EventTypes []string
	SourceDIDs []string
	SessionIDs []string
}

// Matches returns true if the event passes all non-empty filter criteria.
func (f *StreamFilter) Matches(e *StreamEvent) bool {
	if f == nil {
		return true
	}
	if len(f.EventTypes) > 0 && !containsStr(f.EventTypes, e.Type) {
		return false
	}
	if len(f.SourceDIDs) > 0 && !containsStr(f.SourceDIDs, e.Source) {
		return false
	}
	if len(f.SessionIDs) > 0 && !containsStr(f.SessionIDs, e.SessionID) {
		return false
	}
	return true
}

func containsStr(slice []string, s string) bool {
	for _, v := range slice {
		if v == s {
			return true
		}
	}
	return false
}

// Subscription receives filtered events from an EventBus.
type Subscription struct {
	ID             string
	Events         chan StreamEvent
	filter         *StreamFilter
	bus            *EventBus
	closed         bool
	mu             sync.Mutex
	EventsReceived int64
	EventsDropped  int64
}

// Next blocks until the next matching event arrives or the timeout elapses.
// Returns the event and true, or a zero-value event and false on timeout.
func (s *Subscription) Next(timeout time.Duration) (StreamEvent, bool) {
	select {
	case e, ok := <-s.Events:
		if !ok {
			return StreamEvent{}, false
		}
		return e, true
	case <-time.After(timeout):
		return StreamEvent{}, false
	}
}

// Close unsubscribes and drains the event channel.
func (s *Subscription) Close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return
	}
	s.closed = true
	if s.bus != nil {
		s.bus.unsubscribe(s.ID)
	}
}

// IsClosed returns whether the subscription has been closed.
func (s *Subscription) IsClosed() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.closed
}

// EventBusOption configures an EventBus.
type EventBusOption func(*EventBus)

// WithMaxBuffer sets the per-subscriber channel buffer size (default 1000).
func WithMaxBuffer(size int) EventBusOption {
	return func(b *EventBus) {
		b.maxBuffer = size
	}
}

// WithReplaySize sets the replay buffer size (default 100).
func WithReplaySize(size int) EventBusOption {
	return func(b *EventBus) {
		b.replaySize = size
	}
}

// EventBus is the core in-process pub/sub system for ROAR streaming events.
type EventBus struct {
	maxBuffer   int
	replaySize  int
	mu          sync.RWMutex
	subscribers map[string]*Subscription
	replay      []StreamEvent
}

// NewEventBus creates a new EventBus with the given options.
func NewEventBus(opts ...EventBusOption) *EventBus {
	b := &EventBus{
		maxBuffer:   1000,
		replaySize:  100,
		subscribers: make(map[string]*Subscription),
		replay:      make([]StreamEvent, 0),
	}
	for _, opt := range opts {
		opt(b)
	}
	return b
}

// Subscribe creates a new subscription with the given filter and buffer size.
// If replay is true, recent events matching the filter are delivered immediately.
func (b *EventBus) Subscribe(filter *StreamFilter, bufferSize int, replay bool) *Subscription {
	if bufferSize <= 0 {
		bufferSize = b.maxBuffer
	}

	uid := make([]byte, 4)
	_, _ = rand.Read(uid)
	id := "sub_" + hex.EncodeToString(uid)
	sub := &Subscription{
		ID:     id,
		Events: make(chan StreamEvent, bufferSize),
		filter: filter,
		bus:    b,
	}

	b.mu.Lock()
	b.subscribers[id] = sub

	// Replay recent matching events
	if replay {
		for _, e := range b.replay {
			if filter == nil || filter.Matches(&e) {
				select {
				case sub.Events <- e:
					sub.EventsReceived++
				default:
					// Buffer full during replay, skip
				}
			}
		}
	}
	b.mu.Unlock()

	return sub
}

// Publish sends an event to all matching subscribers.
// Returns the number of subscribers that received the event.
func (b *EventBus) Publish(event *StreamEvent) int {
	if event.Timestamp == 0 {
		event.Timestamp = float64(time.Now().UnixMilli()) / 1000.0
	}

	b.mu.Lock()
	// Add to replay buffer with FIFO eviction
	b.replay = append(b.replay, *event)
	for len(b.replay) > b.replaySize {
		b.replay = b.replay[1:]
	}

	// Snapshot subscribers under lock
	subs := make([]*Subscription, 0, len(b.subscribers))
	for _, sub := range b.subscribers {
		subs = append(subs, sub)
	}
	b.mu.Unlock()

	delivered := 0
	for _, sub := range subs {
		if sub.IsClosed() {
			continue
		}
		if sub.filter != nil && !sub.filter.Matches(event) {
			continue
		}

		select {
		case sub.Events <- *event:
			sub.mu.Lock()
			sub.EventsReceived++
			sub.mu.Unlock()
			delivered++
		default:
			// Backpressure: drop oldest event and retry once
			select {
			case <-sub.Events:
				sub.mu.Lock()
				sub.EventsDropped++
				sub.mu.Unlock()
			default:
			}
			select {
			case sub.Events <- *event:
				sub.mu.Lock()
				sub.EventsReceived++
				sub.mu.Unlock()
				delivered++
			default:
				sub.mu.Lock()
				sub.EventsDropped++
				sub.mu.Unlock()
			}
		}
	}

	return delivered
}

// unsubscribe removes a subscription by ID (called from Subscription.Close).
func (b *EventBus) unsubscribe(id string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if sub, ok := b.subscribers[id]; ok {
		close(sub.Events)
		delete(b.subscribers, id)
	}
}

// CloseAll closes all subscriptions and clears the replay buffer.
func (b *EventBus) CloseAll() {
	b.mu.Lock()
	defer b.mu.Unlock()
	for id, sub := range b.subscribers {
		sub.mu.Lock()
		sub.closed = true
		sub.mu.Unlock()
		close(sub.Events)
		delete(b.subscribers, id)
	}
	b.replay = b.replay[:0]
}

// SubscriberCount returns the current number of active subscribers.
func (b *EventBus) SubscriberCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.subscribers)
}

// NewStreamEvent creates a StreamEvent with the current timestamp.
func NewStreamEvent(eventType, source, sessionID string, data map[string]any) StreamEvent {
	return StreamEvent{
		Type:      eventType,
		Source:    source,
		SessionID: sessionID,
		Data:      data,
		Timestamp: float64(time.Now().UnixMilli()) / 1000.0,
	}
}
