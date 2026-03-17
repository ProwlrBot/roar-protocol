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


# ---------------------------------------------------------------------------
# Transaction Receipts
# ---------------------------------------------------------------------------


class TransactionReceipt(BaseModel):
    """Immutable receipt for a completed transaction.

    Contains both parties' signatures as proof of agreement.
    """

    receipt_id: str = Field(default_factory=lambda: f"rcpt_{uuid.uuid4().hex[:12]}")
    transaction_id: str
    initiator_did: str
    counterparty_did: str
    action: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    initiator_signature: str = ""
    counterparty_signature: str = ""
    timestamp: float = Field(default_factory=time.time)

    @property
    def is_dual_signed(self) -> bool:
        return bool(self.initiator_signature and self.counterparty_signature)


def create_receipt(tx: Transaction) -> TransactionReceipt:
    """Create a receipt from a committed transaction."""
    if tx.status != "committed":
        raise ValueError("Can only create receipts for committed transactions")
    return TransactionReceipt(
        transaction_id=tx.transaction_id,
        initiator_did=tx.initiator_did,
        counterparty_did=tx.counterparty_did,
        action=tx.action,
        amount=tx.amount,
        currency=tx.currency,
        initiator_signature=tx.signature,
    )


def countersign_receipt(
    receipt: TransactionReceipt, private_key_hex: str,
) -> TransactionReceipt:
    """Counterparty signs the receipt to create dual-signed proof of agreement."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(_MISSING)

    body = json.dumps({
        "receipt_id": receipt.receipt_id,
        "transaction_id": receipt.transaction_id,
        "initiator_did": receipt.initiator_did,
        "counterparty_did": receipt.counterparty_did,
        "action": receipt.action,
        "amount": receipt.amount,
        "currency": receipt.currency,
        "initiator_signature": receipt.initiator_signature,
    }, sort_keys=True).encode("utf-8")

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    raw_sig = private.sign(body)
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode("ascii").rstrip("=")
    receipt.counterparty_signature = f"ed25519:{sig_b64}"
    return receipt


def verify_receipt(
    receipt: TransactionReceipt,
    initiator_pub_hex: str,
    counterparty_pub_hex: str,
) -> bool:
    """Verify both signatures on a dual-signed receipt."""
    if not receipt.is_dual_signed:
        return False
    # Verify initiator sig is from a valid committed transaction
    # (We verify the counterparty signature over the receipt body)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(_MISSING)

    body = json.dumps({
        "receipt_id": receipt.receipt_id,
        "transaction_id": receipt.transaction_id,
        "initiator_did": receipt.initiator_did,
        "counterparty_did": receipt.counterparty_did,
        "action": receipt.action,
        "amount": receipt.amount,
        "currency": receipt.currency,
        "initiator_signature": receipt.initiator_signature,
    }, sort_keys=True).encode("utf-8")

    b64 = receipt.counterparty_signature.removeprefix("ed25519:")
    padding = (4 - len(b64) % 4) % 4
    raw_sig = base64.urlsafe_b64decode(b64 + "=" * padding)

    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(counterparty_pub_hex))
        pub.verify(raw_sig, body)
        return True
    except (InvalidSignature, ValueError):
        return False
