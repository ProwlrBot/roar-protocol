# -*- coding: utf-8 -*-
"""SQLite-backed agent directory for persistent discovery.

Replaces the in-memory AgentDirectory with durable storage. Agent cards
are serialized as JSON and stored in SQLite. Thread-safe via
``check_same_thread=False``.

Default path: ~/.roar/roar_directory.db

Usage::

    directory = SQLiteAgentDirectory()
    directory.register(card)

    entry = directory.lookup("did:roar:agent:planner-abc12345")
    results = directory.search("code-review")
    directory.close()
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import List, Optional

from .types import AgentCard, DiscoveryEntry

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".roar", "roar_directory.db")


class SQLiteAgentDirectory:
    """SQLite-backed agent directory for persistent agent discovery.

    Same interface as the in-memory ``AgentDirectory`` but persists
    agent cards to disk.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                did TEXT PRIMARY KEY,
                card_json TEXT NOT NULL,
                registered_at REAL NOT NULL,
                last_seen REAL NOT NULL,
                hub_url TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    def register(self, card: AgentCard) -> DiscoveryEntry:
        """Register an agent card in the directory.

        Args:
            card: The agent card to register.

        Returns:
            The created DiscoveryEntry.
        """
        now = time.time()
        entry = DiscoveryEntry(agent_card=card, registered_at=now, last_seen=now)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO agents (did, card_json, registered_at, last_seen, hub_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (card.identity.did, card.model_dump_json(), now, now, ""),
        )
        self._conn.commit()
        logger.debug("Registered agent %s in SQLite directory", card.identity.did)
        return entry

    def unregister(self, did: str) -> bool:
        """Remove an agent from the directory.

        Returns:
            True if the agent was removed, False if not found.
        """
        cursor = self._conn.execute("DELETE FROM agents WHERE did = ?", (did,))
        self._conn.commit()
        removed = cursor.rowcount > 0
        if removed:
            logger.debug("Unregistered agent %s from SQLite directory", did)
        return removed

    def lookup(self, did: str) -> Optional[DiscoveryEntry]:
        """Look up an agent by DID."""
        row = self._conn.execute(
            "SELECT card_json, registered_at, last_seen, hub_url FROM agents WHERE did = ?",
            (did,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def search(self, capability: str) -> List[DiscoveryEntry]:
        """Find agents with a specific capability string."""
        rows = self._conn.execute(
            "SELECT card_json, registered_at, last_seen, hub_url FROM agents"
        ).fetchall()
        results = []
        for row in rows:
            entry = self._row_to_entry(row)
            if capability in entry.agent_card.identity.capabilities:
                results.append(entry)
        return results

    def list_all(self) -> List[DiscoveryEntry]:
        """List all registered agents."""
        rows = self._conn.execute(
            "SELECT card_json, registered_at, last_seen, hub_url FROM agents"
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> DiscoveryEntry:
        card = AgentCard.model_validate_json(row["card_json"])
        return DiscoveryEntry(
            agent_card=card,
            registered_at=row["registered_at"],
            last_seen=row["last_seen"],
            hub_url=row["hub_url"],
        )
