from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def normalize_before_event_deadlines(raw: dict[str, Any], timezone_name: str) -> None:
    """Make a goal's “before this event” deadline an exact event-start deadline."""
    events_by_date: dict[str, list[datetime]] = {}
    timezone = ZoneInfo(timezone_name)
    items = raw.get("items", [])
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "explicit_event":
            continue
        constraints = item.get("hard_constraints")
        if not isinstance(constraints, dict):
            continue
        date_value = constraints.get("fixed_date")
        start_value = constraints.get("fixed_start_time")
        if not date_value or not start_value:
            continue
        try:
            event_start = datetime.fromisoformat(f"{date_value}T{start_value}").replace(tzinfo=timezone)
        except (TypeError, ValueError):
            continue
        events_by_date.setdefault(str(date_value), []).append(event_start)

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "abstract_goal" or "之前" not in item.get("source_text", ""):
            continue
        facts = item.get("facts")
        if not isinstance(facts, dict):
            continue
        constraints = item.setdefault("hard_constraints", {})
        if not isinstance(constraints, dict):
            item["hard_constraints"] = constraints = {}
        deadline_date = facts.get("deadline") or str(constraints.get("must_finish_before", ""))[:10]
        matching_events = events_by_date.get(str(deadline_date), [])
        if len(matching_events) != 1:
            continue
        event_start = matching_events[0]
        constraints["must_finish_before"] = event_start.isoformat()
        provenance = item.setdefault("provenance", [])
        if not isinstance(provenance, list):
            item["provenance"] = provenance = []
        entry = next(
            (value for value in provenance
             if isinstance(value, dict) and value.get("field_path") == "hard_constraints.must_finish_before"),
            None,
        )
        if entry is None:
            provenance.append({
                "field_path": "hard_constraints.must_finish_before",
                "value": event_start.isoformat(),
                "source": "system_derived",
                "reason": "用户说在明确安排之前完成，截止到该安排开始时刻",
                "user_editable": True,
                "display_label": f"须在{event_start:%Y-%m-%d %H:%M}前完成",
            })
        else:
            entry["value"] = event_start.isoformat()
            entry["reason"] = "用户说在明确安排之前完成，截止到该安排开始时刻"
            entry["display_label"] = f"须在{event_start:%Y-%m-%d %H:%M}前完成"
