from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from urllib.parse import urlsplit


SESSION_COOKIE = "onesync_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Session:
    csrf_token: str
    expires_at: float


class SessionManager:
    def __init__(self, admin_token: str, ttl_seconds: int = 12 * 60 * 60) -> None:
        self.admin_token = admin_token
        self.ttl_seconds = ttl_seconds
        self.sessions: dict[str, Session] = {}

    @property
    def configured(self) -> bool:
        return len(self.admin_token) >= 16

    def login(self, token: str) -> tuple[str, Session] | None:
        if not self.configured or not hmac.compare_digest(token, self.admin_token):
            return None
        now = time.time()
        self.sessions = {
            session_id: session
            for session_id, session in self.sessions.items()
            if session.expires_at > now
        }
        if len(self.sessions) >= 256:
            oldest = min(self.sessions, key=lambda item: self.sessions[item].expires_at)
            self.sessions.pop(oldest, None)
        session_id = secrets.token_urlsafe(32)
        session = Session(
            csrf_token=secrets.token_urlsafe(32),
            expires_at=now + self.ttl_seconds,
        )
        self.sessions[session_id] = session
        return session_id, session

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        session = self.sessions.get(session_id)
        if not session:
            return None
        if session.expires_at <= time.time():
            self.sessions.pop(session_id, None)
            return None
        return session

    def logout(self, session_id: str | None) -> None:
        if session_id:
            self.sessions.pop(session_id, None)


class RateLimiter:
    def __init__(self) -> None:
        self.requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, client: str, bucket: str, limit: int, window: int) -> tuple[bool, int]:
        now = time.monotonic()
        entries = self.requests[(client, bucket)]
        while entries and entries[0] <= now - window:
            entries.popleft()
        if len(entries) >= limit:
            retry_after = max(1, int(window - (now - entries[0])) + 1)
            return False, retry_after
        entries.append(now)
        return True, 0


def hostname_from_header(host_header: str) -> str | None:
    try:
        return urlsplit(f"//{host_header}").hostname
    except ValueError:
        return None


def host_is_allowed(host_header: str, configured_hosts: tuple[str, ...]) -> bool:
    hostname = hostname_from_header(host_header)
    if not hostname:
        return False
    hostname = hostname.rstrip(".").lower()
    return hostname in {host.rstrip(".").lower() for host in configured_hosts}


def origin_matches_host(origin: str, host_header: str, request_scheme: str) -> bool:
    if not origin or origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
        origin_host = parsed.hostname
        request_host = hostname_from_header(host_header)
        if (
            not origin_host
            or not request_host
            or parsed.scheme not in {"http", "https"}
            or parsed.scheme != request_scheme
        ):
            return False
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        request_parts = urlsplit(f"//{host_header}")
        request_port = request_parts.port or origin_port
    except ValueError:
        return False
    return (
        origin_host.rstrip(".").lower() == request_host.rstrip(".").lower()
        and origin_port == request_port
    )
