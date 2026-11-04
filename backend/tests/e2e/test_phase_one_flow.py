from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from app.prompts.schemas import PhaseAResult, PhaseBResult
from tests.contract.test_prompt_schemas import phase_a_payload


class GoalLLMService:
    async def run_phase_a(self, context):
        return PhaseAResult.model_validate({
            "decision":"ready","questions":[],"manual_required":None,"global_assumptions":[],
            "items":[{"item_id":"goal_1","kind":"abstract_goal","source_text":"每周一三五晚上散步30分钟","title":"规律散步",
                "facts":{"date":None,"start_time":None,"end_time":None,"duration_minutes":30,"deadline":None,"stated_frequency":"每周三次","activity":"散步","result_metric":None},
                "hard_constraints":{"allowed_weekdays":[1,3,5],"required_periods":["evening"],"fixed_date":None,"fixed_start_time":None},
                "soft_preferences":{"preferred_periods":[]},"provenance":[],"critical_missing":[],"assumptions":[]}]
        })

    async def run_phase_b(self, phase_a, context):
        return PhaseBResult.model_validate({
            "decision":"ready_for_scheduling","fixed_events":[],"assumptions":[],
            "goal_plans":[{"source_item_id":"goal_1","goal_title":"规律散步","deadline":None,"deadline_provenance":None,"importance":"medium","urgency":"low","suggested_goal_horizon_days":56,"assumptions":[],
                "task_templates":[{"task_id":"walk","title":"散步30分钟","activity_type":"walking","instructions":"以舒适速度散步30分钟","duration_minutes":30,"occurrences_within_window":6,"frequency_per_week":3,"min_gap_hours":36,"depends_on":[],
                    "hard_constraints":{"allowed_weekdays":[1,3,5],"required_periods":["evening"],"fixed_date":None,"fixed_start_time":None},"soft_preferences":{"preferred_periods":[]},"source":"user_input","provenance":[],"assumptions":[]}]}]
        })


class MixedLLMService(GoalLLMService):
    async def run_phase_a(self, context):
        goal = (await super().run_phase_a(context)).model_dump(mode="json")
        fixed = phase_a_payload()["items"][0]
        fixed.update({"item_id":"fixed_1", "source_text":"周一18点开会"})
        fixed["facts"].update({"date":"2026-08-31", "start_time":"18:00", "end_time":"19:00"})
        fixed["hard_constraints"].update({"allowed_weekdays":[1], "fixed_date":"2026-08-31", "fixed_start_time":"18:00"})
        goal["items"].append(fixed)
        return PhaseAResult.model_validate(goal)

    async def run_phase_b(self, phase_a, context):
        result = (await super().run_phase_b(phase_a, context)).model_dump(mode="json")
        result["goal_plans"][0]["task_templates"][0]["occurrences_within_window"] = 1
        result["goal_plans"][0]["task_templates"][0]["frequency_per_week"] = 1
        result["goal_plans"][0]["task_templates"][0]["min_gap_hours"] = 0
        result["fixed_events"] = [{
            "source_item_id":"fixed_1", "title":"开会", "date":"2026-08-31",
            "start_time":"18:00", "end_time":"19:00", "duration_minutes":60, "assumptions":[],
        }]
        return PhaseBResult.model_validate(result)


class OverfullAiSuggestionService:
    async def run_phase_a(self, context):
        return PhaseAResult.model_validate({
            "decision": "ready", "questions": [], "manual_required": None, "global_assumptions": [],
            "items": [{
                "item_id": "goal_1", "kind": "abstract_goal", "source_text": "临近面试准备一下",
                "title": "面试准备",
                "facts": {"date": None, "start_time": None, "end_time": None, "duration_minutes": None,
                          "deadline": "2026-09-01", "stated_frequency": None, "activity": "面试准备", "result_metric": None},
                "hard_constraints": {"allowed_weekdays": [], "required_periods": [], "fixed_date": None,
                                     "fixed_start_time": None, "must_finish_before": "2026-09-01T10:00:00+08:00"},
                "soft_preferences": {"preferred_periods": [], "pacing": "distributed"},
                "provenance": [], "critical_missing": [], "assumptions": [],
            }],
        })

    async def run_phase_b(self, phase_a, context):
        return PhaseBResult.model_validate({
            "decision": "ready_for_scheduling", "fixed_events": [], "assumptions": [],
            "goal_plans": [{
                "source_item_id": "goal_1", "goal_title": "面试准备", "deadline": "2026-09-01",
                "deadline_provenance": None, "importance": "high", "urgency": "high",
                "suggested_goal_horizon_days": 1, "assumptions": [], "task_templates": [{
                    "task_id": "prep", "title": "面试准备", "activity_type": "study",
                    "instructions": "复习核心知识点", "duration_minutes": 30,
                    "occurrences_within_window": 4, "frequency_per_week": 3, "min_gap_hours": 0,
                    "depends_on": [],
                    "hard_constraints": {"allowed_weekdays": [], "required_periods": [], "must_finish_before": "2026-09-01T10:00:00+08:00"},
                    "soft_preferences": {"preferred_periods": [], "pacing": "distributed"},
                    "source": "ai_suggestion", "provenance": [], "assumptions": [],
                }],
            }],
        })


class OverfullUserRequirementService(OverfullAiSuggestionService):
    async def run_phase_a(self, context):
        result = (await super().run_phase_a(context)).model_dump(mode="json")
        result["items"][0]["hard_constraints"]["required_occurrences_within_window"] = 4
        return PhaseAResult.model_validate(result)

    async def run_phase_b(self, phase_a, context):
        result = (await super().run_phase_b(phase_a, context)).model_dump(mode="json")
        task = result["goal_plans"][0]["task_templates"][0]
        task["source"] = "user_input"
        task["provenance"] = [{
            "field_path": "task_template.occurrences_within_window", "value": 4,
            "source": "user_input", "reason": "用户明确要求准备4次", "user_editable": True,
            "display_label": "用户输入",
        }]
        return PhaseBResult.model_validate(result)


class OverfullUserRequirementWithGapService(OverfullUserRequirementService):
    async def run_phase_b(self, phase_a, context):
        result = (await super().run_phase_b(phase_a, context)).model_dump(mode="json")
        result["goal_plans"][0]["task_templates"][0]["min_gap_hours"] = 36
        return PhaseBResult.model_validate(result)


class ClarifiedGoalService(GoalLLMService):
    async def run_phase_a(self, context):
        payload = phase_a_payload()
        payload["decision"] = "needs_clarification"
        payload["questions"] = [{
            "question_id": "q_start",
            "priority": 30,
            "missing_field": "facts.start_time",
            "question": "开会几点开始？",
            "covers_item_ids": ["item_1"],
        }]
        return PhaseAResult.model_validate(payload)



def test_goal_is_scheduled_for_14_days_and_confirmed_as_a_group() -> None:
    engine=create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    api=TestClient(create_app(settings=Settings(),session_factory=create_session_factory(engine),llm_service=GoalLLMService()))

    session=api.post("/api/planning/sessions",json={"raw_input":"每周一三五晚上散步30分钟","reference_now":"2026-08-31T09:00:00+08:00"}).json()
    draft=api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()

    assert len(draft["items"]) == 6
    assert all(item["start_at"].split("T")[0] < "2026-09-14" for item in draft["items"])
    assert [item["start_at"][11:16] for item in draft["items"]] == ["18:00"] * 6
    confirmed=api.post(f"/api/drafts/{draft['id']}/confirm",headers={"Idempotency-Key":"goal-flow"})
    assert confirmed.status_code == 200
    assert len(confirmed.json()["event_ids"]) == 6


def test_fixed_event_in_same_input_blocks_goal_candidate() -> None:
    engine=create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    api=TestClient(create_app(settings=Settings(),session_factory=create_session_factory(engine),llm_service=MixedLLMService()))

    session=api.post("/api/planning/sessions",json={"raw_input":"周一18点开会，同时安排散步","reference_now":"2026-08-31T09:00:00+08:00"}).json()
    draft=api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()
    starts = {item["kind"]: item["start_at"] for item in draft["items"]}

    assert starts["fixed"].endswith("T18:00:00+08:00")
    assert starts["scheduled"].endswith("T19:00:00+08:00")


def test_ai_suggested_count_is_reduced_to_the_feasible_capacity() -> None:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    api = TestClient(create_app(settings=Settings(), session_factory=create_session_factory(engine), llm_service=OverfullAiSuggestionService()))

    session = api.post("/api/planning/sessions", json={"raw_input": "临近面试准备一下", "reference_now": "2026-09-01T09:00:00+08:00"}).json()
    draft = api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()

    assert [item["kind"] for item in draft["items"]] == ["scheduled", "scheduled"]
    assert draft["items"][0]["task_template"]["occurrences_within_window"] == 2
    assert draft["items"][0]["provenance"][-1]["source"] == "system_derived"


def test_user_required_count_stays_visible_when_the_deadline_cannot_fit_everything() -> None:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    api = TestClient(create_app(settings=Settings(), session_factory=create_session_factory(engine), llm_service=OverfullUserRequirementService()))

    session = api.post("/api/planning/sessions", json={"raw_input": "面试前必须准备4次", "reference_now": "2026-09-01T09:00:00+08:00"}).json()
    draft = api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()

    assert sorted(item["kind"] for item in draft["items"]) == ["scheduled", "scheduled", "unscheduled"]
    unscheduled = next(item for item in draft["items"] if item["kind"] == "unscheduled")
    assert "用户明确要求" in unscheduled["unscheduled_reason"]


def test_user_required_unscheduled_reason_includes_a_capacity_note() -> None:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    api = TestClient(create_app(settings=Settings(), session_factory=create_session_factory(engine), llm_service=OverfullUserRequirementWithGapService()))

    session = api.post("/api/planning/sessions", json={"raw_input": "面试前必须准备4次", "reference_now": "2026-09-01T09:00:00+08:00"}).json()
    draft = api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()

    assert sorted(item["kind"] for item in draft["items"]) == ["scheduled", "unscheduled"]
    unscheduled = next(item for item in draft["items"] if item["kind"] == "unscheduled")
    assert "用户明确要求" in unscheduled["unscheduled_reason"]
    assert "容量参考" in unscheduled["unscheduled_reason"]
    assert "最多容纳约 1 次" in unscheduled["unscheduled_reason"]
    assert "已排入 1 次" in unscheduled["unscheduled_reason"]


def test_draft_response_includes_the_user_clarifications() -> None:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    api = TestClient(create_app(settings=Settings(), session_factory=create_session_factory(engine), llm_service=ClarifiedGoalService()))

    session = api.post("/api/planning/sessions", json={"raw_input": "9月2日下午开会，顺便安排散步", "reference_now": "2026-08-31T09:00:00+08:00"}).json()
    assert session["status"] == "needs_clarification"
    updated = api.post(f"/api/planning/sessions/{session['id']}/answers", json={"answers": {"q_start": "15:30"}}).json()
    assert updated["status"] == "a_ready"

    draft = api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()

    assert draft["clarifications"] == [{"question": "开会几点开始？", "answer": "15:30"}]
