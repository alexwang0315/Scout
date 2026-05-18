from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from runtime_debug_models import RuntimeDebugEvent, RuntimeDebugEventKind


@dataclass(frozen=True)
class RuntimeDebugAppendResult:
    succeeded: bool
    event: RuntimeDebugEvent | None = None
    error_type: str | None = None
    error_message: str | None = None


class MemoryRuntimeDebugEventLog:
    def __init__(self, events: list[RuntimeDebugEvent] | None = None):
        self._events = list(events or [])

    def append(self, event: RuntimeDebugEvent) -> RuntimeDebugEvent:
        self._events.append(event)
        return event

    def try_append(self, event: RuntimeDebugEvent) -> RuntimeDebugAppendResult:
        try:
            return RuntimeDebugAppendResult(succeeded=True, event=self.append(event))
        except Exception as exc:
            return RuntimeDebugAppendResult(
                succeeded=False,
                event=event,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def list_events(
        self,
        *,
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[RuntimeDebugEvent]:
        events = _filter_events(
            self._events,
            kind=kind,
            since_sequence=since_sequence,
        )
        return _apply_limit(events, limit)


class FileRuntimeDebugEventLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event: RuntimeDebugEvent) -> RuntimeDebugEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    event.model_dump(mode="json"),
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
        return event

    def try_append(self, event: RuntimeDebugEvent) -> RuntimeDebugAppendResult:
        try:
            return RuntimeDebugAppendResult(succeeded=True, event=self.append(event))
        except Exception as exc:
            return RuntimeDebugAppendResult(
                succeeded=False,
                event=event,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def list_events(
        self,
        *,
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[RuntimeDebugEvent]:
        events = _filter_events(
            self._read_events(),
            kind=kind,
            since_sequence=since_sequence,
        )
        return _apply_limit(events, limit)

    def _read_events(self) -> list[RuntimeDebugEvent]:
        if not self.path.exists():
            return []
        events: list[RuntimeDebugEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(RuntimeDebugEvent.model_validate(json.loads(line)))
        return events


def _filter_events(
    events: list[RuntimeDebugEvent],
    *,
    kind: RuntimeDebugEventKind | None,
    since_sequence: int | None,
) -> list[RuntimeDebugEvent]:
    filtered = events
    if kind is not None:
        filtered = [event for event in filtered if event.kind == kind]
    if since_sequence is not None:
        filtered = [event for event in filtered if event.sequence > since_sequence]
    return filtered


def _apply_limit(events: list[RuntimeDebugEvent], limit: int | None) -> list[RuntimeDebugEvent]:
    if limit is None:
        return list(events)
    if limit <= 0:
        return []
    return list(events[-limit:])
