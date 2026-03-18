# -*- coding: utf-8 -*-
"""Shared fixtures for ROAR security penetration tests."""

from __future__ import annotations

import time
from typing import Any

import pytest

from roar_sdk.types import AgentIdentity, ROARMessage


@pytest.fixture
def alice() -> AgentIdentity:
    return AgentIdentity(did="did:roar:agent:alice-sec01", display_name="Alice")


@pytest.fixture
def bob() -> AgentIdentity:
    return AgentIdentity(did="did:roar:agent:bob-sec02", display_name="Bob")


@pytest.fixture
def signing_secret() -> str:
    return "pentest-secret-key-2026"


@pytest.fixture
def valid_message(alice: AgentIdentity, bob: AgentIdentity) -> ROARMessage:
    return ROARMessage(**{"from": alice, "to": bob}, intent="ask", payload={"test": True})


@pytest.fixture
def signed_message(
    valid_message: ROARMessage, signing_secret: str
) -> ROARMessage:
    valid_message.sign(signing_secret)
    return valid_message


def timing_samples(fn: Any, iterations: int = 100) -> list[float]:
    """Collect timing samples for side-channel analysis."""
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        try:
            fn()
        except Exception:
            pass
        end = time.perf_counter_ns()
        samples.append((end - start) / 1e6)
    return samples
