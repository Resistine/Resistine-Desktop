"""Chat history persistence via the app settings system."""
from __future__ import annotations

import time
import uuid

from utils import settings

_NS = "chat_history"
_TITLE_LEN = 40


class ChatHistoryManager:
    """Manage multiple chat sessions persisted in the settings store."""

    def list_sessions(self) -> list[dict]:
        """Return session metadata sorted newest-first."""
        index = settings.get(_NS, "index", default=[])
        return sorted(
            index, key=lambda s: s.get("updated_at", 0), reverse=True)

    def get_active_id(self) -> str | None:
        return settings.get(_NS, "active_id")

    def set_active_id(self, session_id: str | None) -> None:
        settings.set(_NS, "active_id", session_id)

    def create_session(self) -> dict:
        """Create a new empty session and return its metadata."""
        meta = {
            "id": uuid.uuid4().hex[:12],
            "title": "New Chat",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        index = settings.get(_NS, "index", default=[])
        index.append(meta)
        settings.set(_NS, "index", index)
        settings.set(_NS, f"msg_{meta['id']}", [])
        self.set_active_id(meta["id"])
        return meta

    def load_messages(self, session_id: str) -> list[dict]:
        """Load the message list for a session."""
        return settings.get(_NS, f"msg_{session_id}", default=[])

    def save_messages(self, session_id: str, messages: list[dict]) -> None:
        """Persist messages and update the session title / timestamp."""
        try:
            settings.set(_NS, f"msg_{session_id}", messages)
            index = settings.get(_NS, "index", default=[])
            for meta in index:
                if meta["id"] == session_id:
                    if meta["title"] == "New Chat":
                        first_user = next(
                            (m["content"] for m in messages
                             if m["role"] == "user"), None)
                        if first_user:
                            meta["title"] = first_user[:_TITLE_LEN].strip()
                    meta["updated_at"] = time.time()
                    break
            settings.set(_NS, "index", index)
        except Exception as e:
            from utils.logger import logger
            logger.error(f"Failed to save chat messages: {e}")

    def delete_session(self, session_id: str) -> None:
        """Remove a session and its messages."""
        try:
            index = settings.get(_NS, "index", default=[])
            index = [s for s in index if s["id"] != session_id]
            settings.set(_NS, "index", index)
            settings.delete(_NS, f"msg_{session_id}")
            if self.get_active_id() == session_id:
                self.set_active_id(None)
        except Exception as e:
            from utils.logger import logger
            logger.error(f"Failed to delete chat session: {e}")
