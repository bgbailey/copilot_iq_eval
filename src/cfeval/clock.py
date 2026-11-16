"""Clock abstraction so runs can be simulated quickly in tests and demo mode."""

import time
from datetime import datetime, timedelta, timezone


def utc_now():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with millisecond precision and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if "." in text:  # normalize fractional seconds to 6 digits for Python 3.10 fromisoformat
        head, tail = text.split(".", 1)
        idx = 0
        while idx < len(tail) and tail[idx].isdigit():
            idx += 1
        digits = tail[:idx]
        rest = tail[idx:]
        text = "%s.%s%s" % (head, (digits + "000000")[:6], rest)
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SystemClock:
    def now(self):
        return utc_now()

    def sleep(self, seconds):
        if seconds > 0:
            time.sleep(seconds)

    def monotonic(self):
        return time.monotonic()


class SimClock:
    """Simulated clock: sleep() advances time instantly."""

    def __init__(self, start=None):
        self._now = start or utc_now()
        self._mono = 0.0

    def now(self):
        return self._now

    def sleep(self, seconds):
        self.advance(seconds)

    def advance(self, seconds):
        self._now = self._now + timedelta(seconds=seconds)
        self._mono += seconds

    def monotonic(self):
        return self._mono
