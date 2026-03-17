#!/usr/bin/env python3
"""Quickstart 03: HMAC-SHA256 and Ed25519 signing and verification.

Run: python 03_signed_messages.py
"""
import os
from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.signing import generate_keypair, sign_ed25519, verify_ed25519

# --- HMAC-SHA256 signing (symmetric, shared secret) ---
alice = AgentIdentity(display_name="alice", capabilities=["crypto"])
bob = AgentIdentity(display_name="bob", capabilities=["crypto"])
secret = os.environ.get("ROAR_SIGNING_SECRET", "quickstart-demo-key")

msg = ROARMessage(
    **{"from": alice, "to": bob},
    intent=MessageIntent.NOTIFY,
    payload={"text": "Hello Bob, this message is tamper-proof!"},
)

msg.sign(secret)
print(f"HMAC signature: {msg.auth['signature'][:50]}...")
assert msg.verify(secret), "HMAC verification failed!"
print("HMAC-SHA256: verified OK")

# Tamper detection
msg.payload["text"] = "TAMPERED!"
assert not msg.verify(secret), "Should have detected tampering!"
print("HMAC-SHA256: tamper detected OK")

# --- Ed25519 signing (asymmetric, key pair) ---
priv_key, pub_key = generate_keypair()
print(f"\nEd25519 public key: {pub_key[:32]}...")

agent = AgentIdentity(display_name="ed25519-agent", public_key=pub_key)
peer = AgentIdentity(display_name="peer")

msg2 = ROARMessage(
    **{"from": agent, "to": peer},
    intent=MessageIntent.DELEGATE,
    payload={"task": "verify-me"},
)

sign_ed25519(msg2, priv_key)
print(f"Ed25519 signature: {msg2.auth['signature'][:50]}...")
assert verify_ed25519(msg2), "Ed25519 verification failed!"
print("Ed25519: verified OK")

print("\nAll signing demos passed!")
