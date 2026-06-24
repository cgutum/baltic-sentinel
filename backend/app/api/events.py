"""Live event helpers for the UI (shared).

H0 placeholder. Will hold the in-memory event buffer / SSE stream that the
/events route serves once the pipeline produces events (H3+).
"""

# Simple in-memory ring of recent events for the demo UI.
recent_events: list[dict] = []


def push_event(event: dict) -> None:
    recent_events.append(event)
    # Keep only the last 200 events so memory stays bounded during the demo.
    del recent_events[:-200]
