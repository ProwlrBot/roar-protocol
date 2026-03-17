"""Tests for cryptographic audit trail."""

import json
import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.signing import generate_keypair
from roar_sdk.audit import AuditLog, AuditEntry


def _make_msg(sender_name="alice", receiver_name="bob") -> ROARMessage:
    sender = AgentIdentity(display_name=sender_name)
    receiver = AgentIdentity(display_name=receiver_name)
    return ROARMessage(
        **{"from": sender, "to": receiver},
        intent=MessageIntent.DELEGATE,
        payload={"task": "test"},
    )


class TestAuditLog:
    def test_record_single_entry(self):
        priv, pub = generate_keypair()
        log = AuditLog(private_key_hex=priv, public_key_hex=pub)
        msg = _make_msg()
        entry = log.record(msg)
        assert entry.sequence == 0
        assert entry.prev_hash == "genesis"
        assert entry.sender_did == msg.from_identity.did
        assert entry.signature != ""
        assert log.length == 1

    def test_chain_linkage(self):
        priv, pub = generate_keypair()
        log = AuditLog(private_key_hex=priv, public_key_hex=pub)
        e1 = log.record(_make_msg())
        e2 = log.record(_make_msg())
        assert e2.prev_hash == e1.entry_hash
        assert e2.sequence == 1

    def test_verify_chain_valid(self):
        priv, pub = generate_keypair()
        log = AuditLog(private_key_hex=priv, public_key_hex=pub)
        for _ in range(5):
            log.record(_make_msg())
        ok, err = log.verify_chain()
        assert ok, f"Chain verification failed: {err}"

    def test_verify_chain_detects_tampering(self):
        priv, pub = generate_keypair()
        log = AuditLog(private_key_hex=priv, public_key_hex=pub)
        for _ in range(3):
            log.record(_make_msg())

        # Tamper with an entry
        tampered = log._entries[1]
        log._entries[1] = AuditEntry(
            sequence=tampered.sequence,
            timestamp=tampered.timestamp,
            sender_did="did:roar:agent:TAMPERED",
            receiver_did=tampered.receiver_did,
            intent=tampered.intent,
            message_id=tampered.message_id,
            message_hash=tampered.message_hash,
            trace_id=tampered.trace_id,
            prev_hash=tampered.prev_hash,
            entry_hash=tampered.entry_hash,  # hash won't match now
            signature=tampered.signature,
        )
        ok, err = log.verify_chain()
        assert not ok
        assert "tampered" in err.lower() or "hash" in err.lower()

    def test_verify_chain_detects_broken_link(self):
        priv, pub = generate_keypair()
        log = AuditLog(private_key_hex=priv, public_key_hex=pub)
        for _ in range(3):
            log.record(_make_msg())

        # Break the chain by swapping entries
        log._entries[1], log._entries[2] = log._entries[2], log._entries[1]
        ok, err = log.verify_chain()
        assert not ok

    def test_export_and_load_jsonl(self, tmp_path):
        priv, pub = generate_keypair()
        log = AuditLog(private_key_hex=priv, public_key_hex=pub)
        for _ in range(3):
            log.record(_make_msg())

        path = str(tmp_path / "audit.jsonl")
        count = log.export_jsonl(path)
        assert count == 3

        loaded = AuditLog.load_jsonl(path)
        loaded._public_key = pub
        assert loaded.length == 3
        ok, err = loaded.verify_chain(public_key_hex=pub)
        assert ok, f"Loaded chain invalid: {err}"

    def test_query_by_agent(self):
        log = AuditLog()
        msg1 = _make_msg("alice", "bob")
        msg2 = _make_msg("charlie", "bob")
        log.record(msg1)
        log.record(msg2)

        results = log.query(agent_did=msg1.from_identity.did)
        assert len(results) == 1
        assert results[0].sender_did == msg1.from_identity.did

    def test_query_by_intent(self):
        log = AuditLog()
        log.record(_make_msg())
        results = log.query(intent="delegate")
        assert len(results) == 1

    def test_unsigned_log_works(self):
        """Audit log works without signing (no keys)."""
        log = AuditLog()
        log.record(_make_msg())
        log.record(_make_msg())
        ok, err = log.verify_chain()
        assert ok

    def test_trace_id_recorded(self):
        log = AuditLog()
        entry = log.record(_make_msg(), trace_id="trace-abc123")
        assert entry.trace_id == "trace-abc123"
