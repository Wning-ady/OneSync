from __future__ import annotations

import time
from collections import defaultdict, deque
from urllib.parse import urlsplit


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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
