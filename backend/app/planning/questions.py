from typing import Any


PERIOD_START_OPTIONS = {
    "morning": ("08:00", "09:00", "10:00", "11:00"),
    "afternoon": ("13:00", "14:00", "15:00", "16:00", "17:00"),
    "evening": ("18:00", "19:00", "20:00", "21:00"),
}


def present_questions(phase_a_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not phase_a_json:
        return []
    items = {item.get("item_id"): item for item in phase_a_json.get("items", [])}
    presented = []
    for raw_question in phase_a_json.get("questions", []):
        question = dict(raw_question)
        question.setdefault("input_type", "free_text")
        question.setdefault("options", [])
        question.setdefault("allow_custom_input", True)

        if question.get("missing_field") == "facts.start_time":
            covered_items = [items.get(item_id) for item_id in question.get("covers_item_ids", [])]
            periods = {
                period
                for item in covered_items
                if item is not None
                for period in item.get("hard_constraints", {}).get("required_periods", [])
            }
            if len(periods) == 1:
                values = PERIOD_START_OPTIONS.get(next(iter(periods)))
                if values:
                    question["input_type"] = "single_choice"
                    question["options"] = [{"label": value, "value": value} for value in values]
                    question["allow_custom_input"] = True
        presented.append(question)
    return presented
