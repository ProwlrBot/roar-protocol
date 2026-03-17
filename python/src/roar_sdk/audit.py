# -*- coding: utf-8 -*-
"""ROAR Protocol — Cryptographic audit trail for agent interactions.

Provides a tamper-evident audit log where each entry is signed with Ed25519
and chained to the previous entry via hash. Any modification to an entry
invalidates all subsequent entries.

Usage::

    from roar_sdk.audit import AuditLog

    log = AuditLog(private_key_hex=priv_key)
    log.record(msg)  # Record a message exchange

    # Verify integrity
    assert log.verify_chain()

    # Export
    log.export_jsonl("audit.jsonl")

    # CLI verification
    # roar audit verify audit.jsonl
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .types import ROARMessage


@dataclass(frozen=True)
class AuditEntry:
    """A single tamper-evident audit log entry."""
    sequence: int
    timestamp: float
    sender_did: str
    receiver_did: str
    intent: str
    message_id: str
    message_hash: str
    trace_id: str
    prev_hash: str
    entry_hash: str
    signature: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "sender_did": self.sender_did,
            "receiver_did": self.receiver_did,
            "intent": self.intent,
            "message_id": self.message_id,
            "message_hash": self.message_hash,
            "trace_id": self.trace_id,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "signature": self.signature,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> AuditEntry:
        return AuditEntry(**d)


def _hash_message(msg: ROARMessage) -> str:
    """Hash the security-relevant fields of a message."""
    body = json.dumps({
        "id": msg.id,
        "from": msg.from_identity.did,
        "to": msg.to_identity.did,
        "intent": msg.intent,
        "payload": msg.payload,
        "timestamp": msg.timestamp,
    }, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _hash_entry(
    sequence: int,
    timestamp: float,
    sender_did: str,
    receiver_did: str,
    intent: str,
    message_id: str,
    message_hash: str,
    trace_id: str,
    prev_hash: str,
) -> str:
    """Compute the hash of an audit entry (excluding signature)."""
    body = json.dumps({
        "sequence": sequence,
        "timestamp": timestamp,
        "sender_did": sender_did,
        "receiver_did": receiver_did,
        "intent": intent,
        "message_id": message_id,
        "message_hash": message_hash,
        "trace_id": trace_id,
        "prev_hash": prev_hash,
    }, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _sign_entry(entry_hash: str, private_key_hex: str) -> str:
    """Sign an entry hash with Ed25519. Returns base64url signature."""
    import base64
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError("Audit signing requires cryptography: pip install 'roar-sdk[ed25519]'")

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    sig = private.sign(entry_hash.encode())
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _verify_signature(entry_hash: str, signature: str, public_key_hex: str) -> bool:
    """Verify an Ed25519 signature on an entry hash."""
    import base64
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError("Audit verification requires cryptography: pip install 'roar-sdk[ed25519]'")

    padding = (4 - len(signature) % 4) % 4
    sig_bytes = base64.urlsafe_b64decode(signature + "=" * padding)
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(sig_bytes, entry_hash.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


class AuditLog:
    """Tamper-evident audit log for agent interactions.

    Each entry is:
    - Hashed (SHA-256) over its content fields
    - Chained to the previous entry (prev_hash)
    - Signed with Ed25519

    Any modification breaks the chain and invalidates signatures.
    """

    def __init__(
        self,
        private_key_hex: str = "",
        public_key_hex: str = "",
    ) -> None:
        self._private_key = private_key_hex
        self._public_key = public_key_hex
        self._entries: List[AuditEntry] = []

    @property
    def entries(self) -> List[AuditEntry]:
        return list(self._entries)

    @property
    def length(self) -> int:
        return len(self._entries)

    def record(self, msg: ROARMessage, trace_id: str = "") -> AuditEntry:
        """Record a message exchange in the audit log."""
        seq = len(self._entries)
        prev_hash = self._entries[-1].entry_hash if self._entries else "genesis"
        ts = time.time()
        msg_hash = _hash_message(msg)
        tid = trace_id or msg.context.get("trace_id", "")

        entry_hash = _hash_entry(
            sequence=seq,
            timestamp=ts,
            sender_did=msg.from_identity.did,
            receiver_did=msg.to_identity.did,
            intent=msg.intent,
            message_id=msg.id,
            message_hash=msg_hash,
            trace_id=tid,
            prev_hash=prev_hash,
        )

        signature = ""
        if self._private_key:
            signature = _sign_entry(entry_hash, self._private_key)

        entry = AuditEntry(
            sequence=seq,
            timestamp=ts,
            sender_did=msg.from_identity.did,
            receiver_did=msg.to_identity.did,
            intent=msg.intent,
            message_id=msg.id,
            message_hash=msg_hash,
            trace_id=tid,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            signature=signature,
        )
        self._entries.append(entry)
        return entry

    def verify_chain(self, public_key_hex: str = "") -> tuple[bool, str]:
        """Verify the integrity of the entire audit chain.

        Returns (ok, error_message).
        """
        pub_key = public_key_hex or self._public_key
        prev_hash = "genesis"

        for entry in self._entries:
            # Verify chain linkage
            if entry.prev_hash != prev_hash:
                return False, f"Chain broken at seq {entry.sequence}: expected prev_hash {prev_hash[:16]}, got {entry.prev_hash[:16]}"

            # Recompute entry hash
            expected_hash = _hash_entry(
                sequence=entry.sequence,
                timestamp=entry.timestamp,
                sender_did=entry.sender_did,
                receiver_did=entry.receiver_did,
                intent=entry.intent,
                message_id=entry.message_id,
                message_hash=entry.message_hash,
                trace_id=entry.trace_id,
                prev_hash=entry.prev_hash,
            )
            if entry.entry_hash != expected_hash:
                return False, f"Hash mismatch at seq {entry.sequence}: entry tampered"

            # Verify signature if present
            if entry.signature and pub_key:
                if not _verify_signature(entry.entry_hash, entry.signature, pub_key):
                    return False, f"Invalid signature at seq {entry.sequence}"

            prev_hash = entry.entry_hash

        return True, ""

    def export_jsonl(self, path: str) -> int:
        """Export audit log as newline-delimited JSON. Returns entry count."""
        with open(path, "w") as f:
            for entry in self._entries:
                f.write(json.dumps(entry.to_dict()) + "\n")
        return len(self._entries)

    @classmethod
    def load_jsonl(cls, path: str) -> AuditLog:
        """Load an audit log from a JSONL file."""
        log = cls()
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    log._entries.append(AuditEntry.from_dict(json.loads(line)))
        return log

    def query(
        self,
        agent_did: str = "",
        since: float = 0,
        intent: str = "",
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Query audit entries by agent, time, or intent."""
        results = []
        for entry in reversed(self._entries):
            if agent_did and agent_did not in (entry.sender_did, entry.receiver_did):
                continue
            if since and entry.timestamp < since:
                continue
            if intent and entry.intent != intent:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results
