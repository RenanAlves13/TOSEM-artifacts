from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceWriter:
    """Write an auditable, machine-readable event stream for one experiment run."""

    def __init__(self, path: Path, run_metadata: dict[str, Any]) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._sequence = 0
        self.record("run_started", metadata=run_metadata)

    def record(self, event_type: str, **payload: Any) -> None:
        self._sequence += 1
        event = {
            "sequence": self._sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def finish(self, *, status: str, error: str = "") -> None:
        self.record("run_finished", status=status, error=error)
