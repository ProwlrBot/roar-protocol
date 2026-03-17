# -*- coding: utf-8 -*-
"""ROAR Protocol — Agentic Commerce Transaction Signing (Feature-32).

Extends ROAR's Ed25519 signing for commerce and financial scenarios.
Transactions are signed over canonical JSON fields for tamper-proof
purchase authorizations, commits, and refunds between agents.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

_MISSING = (
    "Ed25519 signing requires the 'cryptography' package. "
    "Install it: pip install 'roar-sdk[ed25519]'"
)

TransactionAction = Literal["purchase", "authorize", "commit", "refund"]
TransactionStatus = Literal["pending", "signed", "committed", "rejected"]


class Transaction(BaseModel):
    """A commerce transaction between two ROAR agents."""

    transaction_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    initiator_did: str
    counterparty_did: str
    action: TransactionAction
    amount: Optional[float] = None
    currency: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    signature: str = ""
    status: TransactionStatus = "pending"


def _canonical_bytes(tx: Transaction) -> bytes:
    """Build the canonical signing body for a transaction."""
    body = json.dumps(
        {
            "transaction_id": tx.transaction_id,
            "initiator_did": tx.initiator_did,
            "counterparty_did": tx.counterparty_did,
            "action": tx.action,
            "amount": tx.amount,
            "currency": tx.currency,
            "payload": tx.payload,
            "timestamp": tx.timestamp,
        },
        sort_keys=True,
    )
    return body.encode("utf-8")


def sign_transaction(tx: Transaction, private_key_hex: str) -> Transaction:
    """Sign a Transaction in place; sets signature and status to *signed*."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    raw_sig = private.sign(_canonical_bytes(tx))
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")
    tx.signature = f"ed25519:{sig_b64}"
    tx.status = "signed"
    return tx


def verify_transaction(tx: Transaction, public_key_hex: str) -> bool:
    """Verify the Ed25519 signature on a Transaction. Returns True if valid."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(_MISSING)

    if not tx.signature.startswith("ed25519:"):
        return False

    b64 = tx.signature[len("ed25519:"):]
    padding = (4 - len(b64) % 4) % 4
    raw_sig = base64.urlsafe_b64decode(b64 + "=" * padding)

    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public.verify(raw_sig, _canonical_bytes(tx))
        return True
    except (InvalidSignature, ValueError):
        return False


def create_purchase_authorization(
    initiator_did: str,
    counterparty_did: str,
    amount: float,
    currency: str,
    payload: dict,
    private_key_hex: str,
) -> Transaction:
    """Create and sign a purchase authorization transaction."""
    tx = Transaction(
        initiator_did=initiator_did,
        counterparty_did=counterparty_did,
        action="authorize",
        amount=amount,
        currency=currency,
        payload=payload,
    )
    return sign_transaction(tx, private_key_hex)


def commit_transaction(tx: Transaction, private_key_hex: str) -> Transaction:
    """Transition a signed transaction to *committed* with a fresh signature.

    Raises ValueError if the transaction is not in *signed* status.
    """
    if tx.status != "signed":
        raise ValueError(
            f"Cannot commit transaction in '{tx.status}' status; must be 'signed'."
        )
    tx.action = "commit"
    tx.timestamp = time.time()
    tx.status = "committed"
    # Re-sign over updated canonical fields
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    raw_sig = private.sign(_canonical_bytes(tx))
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")
    tx.signature = f"ed25519:{sig_b64}"
    return tx
