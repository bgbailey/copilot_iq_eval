"""Stage timings for end-to-end telemetry (EvalEvent rows)."""

import time
from contextlib import contextmanager


class Telemetry:
    def __init__(self, run_id, clock):
        self.run_id = run_id
        self.clock = clock
        self.rows = []

    def event(self, stage, duration_ms, ask_id="", status="ok", **details):
        self.rows.append(
            {
                "RunId": self.run_id,
                "AskId": ask_id,
                "EventTimeUtc": self.clock.now(),
                "Stage": stage,
                "DurationMs": round(float(duration_ms), 1),
                "Status": status,
                "Details": details or {},
            }
        )

    @contextmanager
    def stage(self, stage, ask_id="", **details):
        t0_wall, t0 = time.monotonic(), self.clock.monotonic()
        info = dict(details)
        try:
            yield info
        except Exception as exc:
            info["error"] = str(exc)[:500]
            self.event(stage, self._elapsed(t0_wall, t0), ask_id, "error", **info)
            raise
        self.event(stage, self._elapsed(t0_wall, t0), ask_id, info.pop("status", "ok"), **info)

    def _elapsed(self, t0_wall, t0_clock):
        simulated = (self.clock.monotonic() - t0_clock) * 1000.0
        wall = (time.monotonic() - t0_wall) * 1000.0
        return max(simulated, wall)

    def drain(self):
        rows, self.rows = self.rows, []
        return rows
