"""Deterministic local app used only for browser acceptance checks."""

from datetime import datetime, timedelta

from app.config import Settings
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from app.prompts.schemas import PhaseAResult, PhaseBResult
from tests.contract.test_prompt_schemas import phase_a_payload, phase_b_payload
from tests.e2e.test_phase_one_flow import GoalLLMService


class BrowserLLMService:
    model_name = "browser-fixture"

    def __init__(self) -> None:
        self.start_time = "15:00"

    async def run_phase_a(self, context):
        fixed = phase_a_payload()["items"][0]
        fixed["item_id"] = "fixed_1"
        fixed["source_text"] = "周三下午和客户开会，大概一小时"
        fixed["title"] = "客户会议"
        fixed["hard_constraints"]["required_periods"] = ["afternoon"]
        goal = (await GoalLLMService().run_phase_a(context)).model_dump(mode="json")["items"][0]
        goal["hard_constraints"]["required_periods"] = ["after_work"]
        answers = context.get("clarification_answers", {})
        if not answers:
            fixed["facts"]["start_time"] = None
            fixed["facts"]["end_time"] = None
            fixed["hard_constraints"]["fixed_start_time"] = None
            fixed["critical_missing"] = ["facts.start_time"]
            return PhaseAResult.model_validate({
                "decision": "needs_clarification",
                "items": [fixed, goal],
                "questions": [{
                    "question_id": "q_start_time",
                    "priority": 30,
                    "missing_field": "facts.start_time",
                    "question": "周三下午几点开始和客户开会？",
                    "covers_item_ids": ["fixed_1"],
                }],
                "manual_required": None,
                "global_assumptions": [],
            })

        self.start_time = answers["q_start_time"]
        start = datetime.fromisoformat(f"2026-09-02T{self.start_time}:00")
        end = start + timedelta(hours=1)
        fixed["facts"]["start_time"] = self.start_time
        fixed["facts"]["end_time"] = end.strftime("%H:%M")
        fixed["hard_constraints"]["fixed_start_time"] = self.start_time
        fixed["critical_missing"] = []
        return PhaseAResult.model_validate({
            "decision": "ready",
            "items": [fixed, goal],
            "questions": [],
            "manual_required": None,
            "global_assumptions": [],
        })

    async def run_phase_b(self, phase_a, context):
        fixed = phase_b_payload()["fixed_events"][0]
        fixed["source_item_id"] = "fixed_1"
        fixed["title"] = "客户会议"
        fixed["start_time"] = self.start_time
        start = datetime.fromisoformat(f"2026-09-02T{self.start_time}:00")
        fixed["end_time"] = (start + timedelta(hours=1)).strftime("%H:%M")
        goal_plan = (await GoalLLMService().run_phase_b(phase_a, context)).model_dump(mode="json")["goal_plans"][0]
        task = goal_plan["task_templates"][0]
        task.update({
            "title": "下班后快走30分钟",
            "activity_type": "brisk_walking",
            "instructions": "下班后以能正常交谈的速度快走30分钟",
        })
        task["hard_constraints"]["required_periods"] = ["after_work"]
        return PhaseBResult.model_validate({
            "decision": "ready_for_scheduling",
            "fixed_events": [fixed],
            "goal_plans": [goal_plan],
            "assumptions": [],
        })


engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
Base.metadata.create_all(engine)
app = create_app(
    settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
    session_factory=create_session_factory(engine),
    llm_service=BrowserLLMService(),
)
