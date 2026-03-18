use std::collections::VecDeque;
use std::sync::mpsc::{self, RecvTimeoutError, SyncSender, TrySendError};
use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;

use crate::types::StreamEvent;

/// Stream event type constants matching the ROAR spec Layer 5.
pub const EVENT_TOOL_CALL: &str = "tool_call";
pub const EVENT_MCP_REQUEST: &str = "mcp_request";
pub const EVENT_REASONING: &str = "reasoning";
pub const EVENT_TASK_UPDATE: &str = "task_update";
pub const EVENT_MONITOR_ALERT: &str = "monitor_alert";
pub const EVENT_AGENT_STATUS: &str = "agent_status";
pub const EVENT_CHECKPOINT: &str = "checkpoint";
pub const EVENT_WORLD_UPDATE: &str = "world_update";

/// Filters events by type, source DID, or session ID.
/// All non-empty criteria use AND logic.
#[derive(Debug, Clone, Default)]
pub struct StreamFilter {
    pub event_types: Vec<String>,
    pub source_dids: Vec<String>,
    pub session_ids: Vec<String>,
}

impl StreamFilter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Returns true if the event passes all non-empty filter criteria.
    pub fn matches(&self, event: &StreamEvent) -> bool {
        if !self.event_types.is_empty() && !self.event_types.contains(&event.type_) {
            return false;
        }
        if !self.source_dids.is_empty() && !self.source_dids.contains(&event.source) {
            return false;
        }
        if !self.session_ids.is_empty() && !self.session_ids.contains(&event.session_id) {
            return false;
        }
        true
    }
}

/// Receives filtered events from an EventBus.
pub struct Subscription {
    pub id: String,
    receiver: mpsc::Receiver<StreamEvent>,
    closed: Arc<Mutex<bool>>,
    pub events_received: u64,
    pub events_dropped: u64,
}

impl Subscription {
    /// Blocks until the next event arrives or the timeout elapses.
    pub fn next(&mut self, timeout: Duration) -> Option<StreamEvent> {
        match self.receiver.recv_timeout(timeout) {
            Ok(event) => {
                self.events_received += 1;
                Some(event)
            }
            Err(RecvTimeoutError::Timeout) => None,
            Err(RecvTimeoutError::Disconnected) => None,
        }
    }

    /// Close this subscription.
    pub fn close(&mut self) {
        let mut closed = self.closed.lock().unwrap();
        *closed = true;
    }

    /// Returns whether this subscription is closed.
    pub fn is_closed(&self) -> bool {
        *self.closed.lock().unwrap()
    }
}

struct SubscriberEntry {
    id: String,
    filter: StreamFilter,
    sender: SyncSender<StreamEvent>,
    closed: Arc<Mutex<bool>>,
    dropped: Arc<Mutex<u64>>,
}

/// In-process pub/sub system for ROAR streaming events.
pub struct EventBus {
    max_buffer: usize,
    replay_size: usize,
    replay: RwLock<VecDeque<StreamEvent>>,
    subscribers: RwLock<Vec<SubscriberEntry>>,
}

impl EventBus {
    /// Create a new EventBus with the given buffer and replay sizes.
    pub fn new(max_buffer: usize, replay_size: usize) -> Self {
        Self {
            max_buffer,
            replay_size,
            replay: RwLock::new(VecDeque::new()),
            subscribers: RwLock::new(Vec::new()),
        }
    }

    /// Create an EventBus with default settings (buffer=1000, replay=100).
    pub fn default_bus() -> Self {
        Self::new(1000, 100)
    }

    /// Subscribe to events with an optional filter.
    /// If replay is true, recent matching events are delivered immediately.
    pub fn subscribe(
        &self,
        filter: StreamFilter,
        buffer_size: Option<usize>,
        replay: bool,
    ) -> Subscription {
        let buf = buffer_size.unwrap_or(self.max_buffer);
        let (sender, receiver) = mpsc::sync_channel(buf);
        let id = format!("sub_{}", uuid::Uuid::new_v4().to_string().get(..8).unwrap_or("00000000"));
        let closed = Arc::new(Mutex::new(false));
        let dropped = Arc::new(Mutex::new(0u64));

        // Replay recent matching events
        if replay {
            let replay_buf = self.replay.read().unwrap();
            for event in replay_buf.iter() {
                if filter.matches(event) {
                    let _ = sender.try_send(event.clone());
                }
            }
        }

        let entry = SubscriberEntry {
            id: id.clone(),
            filter: filter,
            sender,
            closed: Arc::clone(&closed),
            dropped: Arc::clone(&dropped),
        };

        self.subscribers.write().unwrap().push(entry);

        Subscription {
            id,
            receiver,
            closed,
            events_received: 0,
            events_dropped: 0,
        }
    }

    /// Publish an event to all matching subscribers.
    /// Returns the number of subscribers that received the event.
    pub fn publish(&self, event: &StreamEvent) -> usize {
        // Add to replay buffer
        {
            let mut replay = self.replay.write().unwrap();
            replay.push_back(event.clone());
            while replay.len() > self.replay_size {
                replay.pop_front();
            }
        }

        let subs = self.subscribers.read().unwrap();
        let mut delivered = 0;

        for sub in subs.iter() {
            if *sub.closed.lock().unwrap() {
                continue;
            }
            if !sub.filter.matches(event) {
                continue;
            }

            match sub.sender.try_send(event.clone()) {
                Ok(()) => {
                    delivered += 1;
                }
                Err(TrySendError::Full(_)) => {
                    // Backpressure: drop oldest, retry once
                    // We can't drain from sender side, so count as dropped
                    let mut d = sub.dropped.lock().unwrap();
                    *d += 1;
                    // Try again — channel may have space after receiver reads
                    if sub.sender.try_send(event.clone()).is_ok() {
                        delivered += 1;
                    } else {
                        *d += 1;
                    }
                }
                Err(TrySendError::Disconnected(_)) => {
                    // Receiver dropped, mark as closed
                    *sub.closed.lock().unwrap() = true;
                }
            }
        }

        delivered
    }

    /// Remove closed subscribers.
    pub fn cleanup(&self) {
        let mut subs = self.subscribers.write().unwrap();
        subs.retain(|s| !*s.closed.lock().unwrap());
    }

    /// Returns the current number of active subscribers.
    pub fn subscriber_count(&self) -> usize {
        let subs = self.subscribers.read().unwrap();
        subs.iter().filter(|s| !*s.closed.lock().unwrap()).count()
    }

    /// Close all subscriptions and clear the replay buffer.
    pub fn close_all(&self) {
        let mut subs = self.subscribers.write().unwrap();
        for sub in subs.iter() {
            *sub.closed.lock().unwrap() = true;
        }
        subs.clear();
        self.replay.write().unwrap().clear();
    }
}

// ---------------------------------------------------------------------------
// Helper to create a StreamEvent with the current timestamp
// ---------------------------------------------------------------------------

/// Create a new StreamEvent with the current Unix timestamp.
pub fn new_stream_event(
    event_type: &str,
    source: &str,
    session_id: &str,
    data: serde_json::Value,
) -> StreamEvent {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    StreamEvent {
        type_: event_type.to_string(),
        source: source.to_string(),
        session_id: session_id.to_string(),
        data,
        timestamp: ts,
        trace_id: String::new(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_publish_subscribe() {
        let bus = EventBus::default_bus();
        let mut sub = bus.subscribe(StreamFilter::new(), None, false);

        let event = new_stream_event(
            EVENT_TASK_UPDATE,
            "did:roar:agent:test-1234",
            "sess-1",
            json!({"status": "running"}),
        );
        let delivered = bus.publish(&event);
        assert_eq!(delivered, 1);

        let got = sub.next(Duration::from_secs(1)).expect("should receive event");
        assert_eq!(got.type_, EVENT_TASK_UPDATE);
        assert_eq!(got.source, "did:roar:agent:test-1234");
    }

    #[test]
    fn test_filter_matches() {
        let event = new_stream_event(
            EVENT_TOOL_CALL,
            "did:roar:agent:alice",
            "sess-42",
            json!({}),
        );

        // Empty filter matches all
        assert!(StreamFilter::new().matches(&event));

        // Matching type
        let f = StreamFilter {
            event_types: vec![EVENT_TOOL_CALL.to_string()],
            ..Default::default()
        };
        assert!(f.matches(&event));

        // Non-matching type
        let f = StreamFilter {
            event_types: vec![EVENT_REASONING.to_string()],
            ..Default::default()
        };
        assert!(!f.matches(&event));

        // Matching source
        let f = StreamFilter {
            source_dids: vec!["did:roar:agent:alice".to_string()],
            ..Default::default()
        };
        assert!(f.matches(&event));

        // AND logic: type matches, source doesn't
        let f = StreamFilter {
            event_types: vec![EVENT_TOOL_CALL.to_string()],
            source_dids: vec!["did:roar:agent:bob".to_string()],
            ..Default::default()
        };
        assert!(!f.matches(&event));
    }

    #[test]
    fn test_replay_buffer() {
        let bus = EventBus::new(1000, 5);

        for i in 0..3 {
            let e = new_stream_event(
                EVENT_AGENT_STATUS,
                "did:roar:agent:test",
                "s1",
                json!({"seq": i}),
            );
            bus.publish(&e);
        }

        // Subscribe with replay
        let mut sub = bus.subscribe(StreamFilter::new(), None, true);

        for i in 0..3 {
            let got = sub.next(Duration::from_secs(1)).expect("should replay");
            assert_eq!(got.data["seq"], i);
        }

        // No more
        assert!(sub.next(Duration::from_millis(50)).is_none());
    }

    #[test]
    fn test_replay_eviction() {
        let bus = EventBus::new(1000, 3);

        for i in 0..5 {
            let e = new_stream_event(EVENT_CHECKPOINT, "did:roar:agent:test", "s1", json!({"seq": i}));
            bus.publish(&e);
        }

        let mut sub = bus.subscribe(StreamFilter::new(), None, true);

        // Should only get last 3: seq 2, 3, 4
        for expected in 2..5 {
            let got = sub.next(Duration::from_secs(1)).expect("should replay");
            assert_eq!(got.data["seq"], expected);
        }
        assert!(sub.next(Duration::from_millis(50)).is_none());
    }

    #[test]
    fn test_close_subscription() {
        let bus = EventBus::default_bus();
        let mut sub = bus.subscribe(StreamFilter::new(), None, false);

        assert_eq!(bus.subscriber_count(), 1);
        sub.close();
        assert!(sub.is_closed());
        assert_eq!(bus.subscriber_count(), 0);
    }

    #[test]
    fn test_multiple_subscribers() {
        let bus = EventBus::default_bus();

        let mut sub_all = bus.subscribe(StreamFilter::new(), None, false);
        let mut sub_tool = bus.subscribe(
            StreamFilter {
                event_types: vec![EVENT_TOOL_CALL.to_string()],
                ..Default::default()
            },
            None,
            false,
        );
        let mut sub_reason = bus.subscribe(
            StreamFilter {
                event_types: vec![EVENT_REASONING.to_string()],
                ..Default::default()
            },
            None,
            false,
        );

        let e = new_stream_event(EVENT_TOOL_CALL, "did:roar:agent:test", "s1", json!({}));
        let delivered = bus.publish(&e);
        assert_eq!(delivered, 2); // sub_all + sub_tool

        assert!(sub_all.next(Duration::from_secs(1)).is_some());
        assert!(sub_tool.next(Duration::from_secs(1)).is_some());
        assert!(sub_reason.next(Duration::from_millis(50)).is_none());
    }

    #[test]
    fn test_close_all() {
        let bus = EventBus::default_bus();
        let sub1 = bus.subscribe(StreamFilter::new(), None, false);
        let sub2 = bus.subscribe(StreamFilter::new(), None, false);

        bus.close_all();

        assert_eq!(bus.subscriber_count(), 0);
        assert!(sub1.is_closed());
        assert!(sub2.is_closed());
    }

    #[test]
    fn test_filtered_replay() {
        let bus = EventBus::default_bus();

        let e1 = new_stream_event(EVENT_TOOL_CALL, "did:roar:agent:alice", "s1", json!({}));
        let e2 = new_stream_event(EVENT_REASONING, "did:roar:agent:bob", "s1", json!({}));
        let e3 = new_stream_event(EVENT_TOOL_CALL, "did:roar:agent:charlie", "s1", json!({}));
        bus.publish(&e1);
        bus.publish(&e2);
        bus.publish(&e3);

        let mut sub = bus.subscribe(
            StreamFilter {
                event_types: vec![EVENT_TOOL_CALL.to_string()],
                ..Default::default()
            },
            None,
            true,
        );

        let got1 = sub.next(Duration::from_secs(1)).expect("should replay e1");
        assert_eq!(got1.source, "did:roar:agent:alice");
        let got2 = sub.next(Duration::from_secs(1)).expect("should replay e3");
        assert_eq!(got2.source, "did:roar:agent:charlie");
        assert!(sub.next(Duration::from_millis(50)).is_none());
    }
}
