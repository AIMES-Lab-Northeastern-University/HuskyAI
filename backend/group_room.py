"""In-memory room manager for live group-challenge chats.

SINGLE-WORKER ONLY. Rooms live in this process's memory, so every member of a
group must be served by the same Uvicorn worker. The deploy runs one worker
(see nixpacks.toml and main.py — neither passes --workers). If HuskyAI ever
scales to multiple workers, this broadcast model breaks and must move to a
shared bus (e.g. Redis pub/sub).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("group_chat")


class GroupRoom:
    """Live state for one group session: the connected sockets, the shared
    conversation history, and a lock that serializes AI turns."""

    def __init__(self, group_session_id: str):
        self.group_session_id = group_session_id
        # ws -> {"user_id": str, "name": str}
        self.connections: dict[WebSocket, dict] = {}
        # Legacy /ws/group only: one shared coach, so one AI turn at a time.
        # The collaborative-study design (/ws/coach) gives every student their
        # own coach and uses per-user locks below instead — private coaches
        # running concurrently is the whole point of that design, so they must
        # not serialise behind each other.
        self.turn_lock = asyncio.Lock()
        # Shared server-side conversation history (same shape as the single-user
        # handler's local list: {"role", "content", optional "attachments"}).
        self.history: list[dict] = []
        self.history_loaded = False

        # --- Collaborative study: N private coaches in one room ---
        # user_id -> {"history": list[dict], "loaded": bool, "conversation_id": str}
        self.private: dict[str, dict] = {}
        # user_id -> Lock. One in-flight coach turn per student, independent of
        # every teammate's.
        self._user_locks: dict[str, asyncio.Lock] = {}
        # Set once the artifact row exists, so teammates' sockets can skip the
        # get-or-create round trip.
        self.artifact_id: str | None = None

    def user_lock(self, user_id: str) -> asyncio.Lock:
        """This student's coach-turn lock. Created on first use."""
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        return lock

    def private_state(self, user_id: str, conversation_id: str) -> dict:
        """This student's private coach history, created empty on first use."""
        st = self.private.get(user_id)
        if st is None:
            st = {"history": [], "loaded": False, "conversation_id": conversation_id}
            self.private[user_id] = st
        return st

    async def send_to_user(self, user_id: str, payload: dict) -> None:
        """Deliver to every socket belonging to one student (they may have
        several tabs). Used for private coach output, which teammates must not
        see — sending it through broadcast() would leak one student's coaching
        into the shared room and destroy the independence the design rests on."""
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws, meta in list(self.connections.items()):
            if meta.get("user_id") != user_id:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.pop(ws, None)

    async def broadcast(self, payload: dict, exclude: WebSocket | None = None) -> None:
        """Send a JSON payload to every connected socket (optionally skipping one).
        Sockets that error are dropped from the roster."""
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            if ws is exclude:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.pop(ws, None)

    def add(self, ws: WebSocket, user_id: str, name: str) -> None:
        self.connections[ws] = {"user_id": user_id, "name": name}

    def remove(self, ws: WebSocket) -> None:
        self.connections.pop(ws, None)

    def members_snapshot(self) -> list[dict]:
        """Distinct connected users (a user may have multiple tabs open)."""
        seen: dict[str, str] = {}
        for meta in self.connections.values():
            seen.setdefault(meta["user_id"], meta["name"])
        return [{"user_id": uid, "name": nm} for uid, nm in seen.items()]


class RoomManager:
    def __init__(self):
        self._rooms: dict[str, GroupRoom] = {}
        self._guard = asyncio.Lock()

    async def get(self, group_session_id: str) -> GroupRoom:
        async with self._guard:
            room = self._rooms.get(group_session_id)
            if room is None:
                room = GroupRoom(group_session_id)
                self._rooms[group_session_id] = room
            return room

    def peek(self, group_session_id: str) -> GroupRoom | None:
        """Return the live room if one exists, without creating it."""
        return self._rooms.get(group_session_id)

    async def drop_if_empty(self, group_session_id: str) -> None:
        async with self._guard:
            room = self._rooms.get(group_session_id)
            if room is not None and not room.connections:
                self._rooms.pop(group_session_id, None)


rooms = RoomManager()
