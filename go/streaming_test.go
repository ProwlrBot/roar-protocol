package roar

import (
	"sync"
	"testing"
	"time"
)

func TestEventBusPublishSubscribe(t *testing.T) {
	bus := NewEventBus()
	sub := bus.Subscribe(nil, 10, false)
	defer sub.Close()

	event := NewStreamEvent(EventTaskUpdate, "did:roar:agent:test-1234", "sess-1", map[string]any{
		"status": "running",
	})

	delivered := bus.Publish(&event)
	if delivered != 1 {
		t.Fatalf("expected 1 delivery, got %d", delivered)
	}

	got, ok := sub.Next(time.Second)
	if !ok {
		t.Fatal("expected event, got timeout")
	}
	if got.Type != EventTaskUpdate {
		t.Errorf("expected type %s, got %s", EventTaskUpdate, got.Type)
	}
	if got.Source != "did:roar:agent:test-1234" {
		t.Errorf("expected source did:roar:agent:test-1234, got %s", got.Source)
	}
}

func TestStreamFilterMatches(t *testing.T) {
	event := StreamEvent{
		Type:      EventToolCall,
		Source:    "did:roar:agent:alice-0001",
		SessionID: "sess-42",
	}

	tests := []struct {
		name   string
		filter StreamFilter
		want   bool
	}{
		{"empty filter matches all", StreamFilter{}, true},
		{"matching type", StreamFilter{EventTypes: []string{EventToolCall}}, true},
		{"non-matching type", StreamFilter{EventTypes: []string{EventReasoning}}, false},
		{"matching source", StreamFilter{SourceDIDs: []string{"did:roar:agent:alice-0001"}}, true},
		{"non-matching source", StreamFilter{SourceDIDs: []string{"did:roar:agent:bob-0002"}}, false},
		{"matching session", StreamFilter{SessionIDs: []string{"sess-42"}}, true},
		{"non-matching session", StreamFilter{SessionIDs: []string{"sess-99"}}, false},
		{"AND logic: type+source match", StreamFilter{
			EventTypes: []string{EventToolCall},
			SourceDIDs: []string{"did:roar:agent:alice-0001"},
		}, true},
		{"AND logic: type matches but source doesn't", StreamFilter{
			EventTypes: []string{EventToolCall},
			SourceDIDs: []string{"did:roar:agent:bob-0002"},
		}, false},
		{"multiple types", StreamFilter{EventTypes: []string{EventReasoning, EventToolCall}}, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.filter.Matches(&event)
			if got != tt.want {
				t.Errorf("Matches() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestNilFilterMatchesAll(t *testing.T) {
	var f *StreamFilter
	event := StreamEvent{Type: EventReasoning}
	if !f.Matches(&event) {
		t.Error("nil filter should match all events")
	}
}

func TestBackpressureDropsOldest(t *testing.T) {
	bus := NewEventBus()
	// Buffer size of 2
	sub := bus.Subscribe(nil, 2, false)
	defer sub.Close()

	// Publish 3 events — the 3rd should trigger backpressure
	for i := 0; i < 3; i++ {
		e := NewStreamEvent(EventTaskUpdate, "did:roar:agent:test", "s1", map[string]any{
			"seq": i,
		})
		bus.Publish(&e)
	}

	// Should get the last 2 events (oldest dropped)
	got1, ok1 := sub.Next(time.Second)
	got2, ok2 := sub.Next(time.Second)
	if !ok1 || !ok2 {
		t.Fatal("expected 2 events")
	}

	// First event (seq=0) should have been dropped
	seq1 := int(got1.Data["seq"].(int))
	seq2 := int(got2.Data["seq"].(int))
	if seq1 != 1 || seq2 != 2 {
		t.Errorf("expected seq 1,2 after backpressure, got %d,%d", seq1, seq2)
	}

	// Verify dropped count
	sub.mu.Lock()
	dropped := sub.EventsDropped
	sub.mu.Unlock()
	if dropped < 1 {
		t.Errorf("expected at least 1 dropped event, got %d", dropped)
	}
}

func TestReplayBuffer(t *testing.T) {
	bus := NewEventBus(WithReplaySize(5))

	// Publish 3 events before subscribing
	for i := 0; i < 3; i++ {
		e := NewStreamEvent(EventAgentStatus, "did:roar:agent:test", "s1", map[string]any{
			"seq": i,
		})
		bus.Publish(&e)
	}

	// Subscribe with replay
	sub := bus.Subscribe(nil, 10, true)
	defer sub.Close()

	// Should receive all 3 replayed events
	for i := 0; i < 3; i++ {
		got, ok := sub.Next(time.Second)
		if !ok {
			t.Fatalf("expected replayed event %d, got timeout", i)
		}
		seq := int(got.Data["seq"].(int))
		if seq != i {
			t.Errorf("expected seq %d, got %d", i, seq)
		}
	}
}

func TestReplayBufferEviction(t *testing.T) {
	bus := NewEventBus(WithReplaySize(3))

	// Publish 5 events — replay should only keep last 3
	for i := 0; i < 5; i++ {
		e := NewStreamEvent(EventCheckpoint, "did:roar:agent:test", "s1", map[string]any{
			"seq": i,
		})
		bus.Publish(&e)
	}

	sub := bus.Subscribe(nil, 10, true)
	defer sub.Close()

	// Should only get events 2, 3, 4
	for expected := 2; expected < 5; expected++ {
		got, ok := sub.Next(time.Second)
		if !ok {
			t.Fatalf("expected replayed event seq=%d, got timeout", expected)
		}
		seq := int(got.Data["seq"].(int))
		if seq != expected {
			t.Errorf("expected seq %d, got %d", expected, seq)
		}
	}

	// No more events
	_, ok := sub.Next(50 * time.Millisecond)
	if ok {
		t.Error("expected no more events after replay")
	}
}

func TestReplayWithFilter(t *testing.T) {
	bus := NewEventBus()

	e1 := NewStreamEvent(EventToolCall, "did:roar:agent:alice", "s1", nil)
	e2 := NewStreamEvent(EventReasoning, "did:roar:agent:bob", "s1", nil)
	e3 := NewStreamEvent(EventToolCall, "did:roar:agent:charlie", "s1", nil)
	bus.Publish(&e1)
	bus.Publish(&e2)
	bus.Publish(&e3)

	// Subscribe with filter for tool_call only
	filter := &StreamFilter{EventTypes: []string{EventToolCall}}
	sub := bus.Subscribe(filter, 10, true)
	defer sub.Close()

	// Should get 2 replayed events (e1 and e3, not e2)
	got1, ok1 := sub.Next(time.Second)
	got2, ok2 := sub.Next(time.Second)
	if !ok1 || !ok2 {
		t.Fatal("expected 2 replayed events")
	}
	if got1.Source != "did:roar:agent:alice" || got2.Source != "did:roar:agent:charlie" {
		t.Errorf("unexpected sources: %s, %s", got1.Source, got2.Source)
	}

	_, ok := sub.Next(50 * time.Millisecond)
	if ok {
		t.Error("expected no more events")
	}
}

func TestSubscriptionClose(t *testing.T) {
	bus := NewEventBus()
	sub := bus.Subscribe(nil, 10, false)

	if bus.SubscriberCount() != 1 {
		t.Fatalf("expected 1 subscriber, got %d", bus.SubscriberCount())
	}

	sub.Close()

	if bus.SubscriberCount() != 0 {
		t.Errorf("expected 0 subscribers after close, got %d", bus.SubscriberCount())
	}

	if !sub.IsClosed() {
		t.Error("expected subscription to be closed")
	}

	// Double-close should be safe
	sub.Close()
}

func TestMultipleSubscribers(t *testing.T) {
	bus := NewEventBus()
	sub1 := bus.Subscribe(nil, 10, false)
	sub2 := bus.Subscribe(&StreamFilter{EventTypes: []string{EventToolCall}}, 10, false)
	sub3 := bus.Subscribe(&StreamFilter{EventTypes: []string{EventReasoning}}, 10, false)
	defer sub1.Close()
	defer sub2.Close()
	defer sub3.Close()

	e := NewStreamEvent(EventToolCall, "did:roar:agent:test", "s1", nil)
	delivered := bus.Publish(&e)

	// sub1 (no filter) and sub2 (tool_call) should get it, but not sub3 (reasoning)
	if delivered != 2 {
		t.Errorf("expected 2 deliveries, got %d", delivered)
	}

	_, ok1 := sub1.Next(time.Second)
	_, ok2 := sub2.Next(time.Second)
	_, ok3 := sub3.Next(50 * time.Millisecond)

	if !ok1 {
		t.Error("sub1 should have received event")
	}
	if !ok2 {
		t.Error("sub2 should have received event")
	}
	if ok3 {
		t.Error("sub3 should NOT have received event")
	}
}

func TestConcurrentPublish(t *testing.T) {
	bus := NewEventBus()
	sub := bus.Subscribe(nil, 1000, false)
	defer sub.Close()

	var wg sync.WaitGroup
	numGoroutines := 10
	eventsPerGoroutine := 100

	for g := 0; g < numGoroutines; g++ {
		wg.Add(1)
		go func(gid int) {
			defer wg.Done()
			for i := 0; i < eventsPerGoroutine; i++ {
				e := NewStreamEvent(EventTaskUpdate, "did:roar:agent:test", "s1", map[string]any{
					"goroutine": gid,
					"seq":       i,
				})
				bus.Publish(&e)
			}
		}(g)
	}

	wg.Wait()

	total := numGoroutines * eventsPerGoroutine
	received := 0
	for {
		_, ok := sub.Next(100 * time.Millisecond)
		if !ok {
			break
		}
		received++
	}

	if received != total {
		t.Errorf("expected %d events, received %d", total, received)
	}
}

func TestCloseAll(t *testing.T) {
	bus := NewEventBus()
	sub1 := bus.Subscribe(nil, 10, false)
	sub2 := bus.Subscribe(nil, 10, false)

	bus.CloseAll()

	if bus.SubscriberCount() != 0 {
		t.Errorf("expected 0 subscribers, got %d", bus.SubscriberCount())
	}
	if !sub1.IsClosed() || !sub2.IsClosed() {
		t.Error("all subscriptions should be closed")
	}
}

func TestNewStreamEvent(t *testing.T) {
	e := NewStreamEvent(EventMonitorAlert, "did:roar:agent:monitor", "sess-7", map[string]any{
		"level": "warning",
	})

	if e.Type != EventMonitorAlert {
		t.Errorf("expected type %s, got %s", EventMonitorAlert, e.Type)
	}
	if e.Source != "did:roar:agent:monitor" {
		t.Errorf("unexpected source: %s", e.Source)
	}
	if e.Timestamp == 0 {
		t.Error("timestamp should be set")
	}
	if e.Data["level"] != "warning" {
		t.Error("data should contain level=warning")
	}
}
