from copy import deepcopy
from datetime import datetime, time
from time import perf_counter
from typing import Any
import re

from pydantic import ValidationError

from app.domain.enums import PhaseADecision, PlanningStatus
from app.llm.service import ModelOutputValidationError
from app.persistence.repositories import ModelRunRepository
from app.planning.phase_a_normalization import normalize_before_event_deadlines
from app.planning.horizon import planning_window_days
from app.prompts.phase_a import PROMPT_VERSION as PHASE_A_VERSION
from app.prompts.phase_b import PROMPT_VERSION as PHASE_B_VERSION
from app.prompts.schemas import PhaseAResult


class InvalidStateTransition(RuntimeError):
    pass


PERIOD_DEFAULT_START_TIMES = {
    "morning": ("09:00", "morning", "上午"),
    "上午": ("09:00", "morning", "上午"),
    "afternoon": ("14:00", "afternoon", "下午"),
    "下午": ("14:00", "afternoon", "下午"),
    "evening": ("19:00", "evening", "晚上"),
    "晚上": ("19:00", "evening", "晚上"),
}

_FULLWIDTH_TRANS = str.maketrans("０１２３４５６７８９：", "0123456789:")
_CN_DIGITS = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_DATE_HINT_PATTERN = re.compile(
    r"今天|明天|后天|大后天|昨天|昨日|每周|本周|下周|上周"
    r"|周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]"
    r"|[0-9]{1,2}[日号]|[零一二两三四五六七八九十]+月"
)
_CLOCK_PATTERN = re.compile(
    r"(上午|早上|凌晨|中午|下午|傍晚|晚上)?"
    r"([0-9]{1,2}|[零一二两三四五六七八九十]{1,3})点"
    r"(半|[0-9]{1,2}|[零一二两三四五六七八九十]{1,2})?分?"
)


def _chinese_number(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left) if left else 1
        ones = _CN_DIGITS.get(right) if right else 0
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return _CN_DIGITS.get(text)


def parse_time_answer(raw: str, *, required_periods: tuple[str, ...] | list[str] = ()) -> time | None:
    """Parse common plain clock answers ("14：00", "下午3点半", "15点30分", "两点半").

    Returns None for anything ambiguous — including relative dates such as
    "明天下午两点" — so the model resolves those with full context instead.
    """
    value = (raw or "").strip().translate(_FULLWIDTH_TRANS).replace(" ", "")
    if not value or _DATE_HINT_PATTERN.search(value):
        return None
    direct = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})", value)
    if direct:
        hour, minute = int(direct[1]), int(direct[2])
        return time(hour, minute) if hour <= 23 and minute <= 59 else None
    match = _CLOCK_PATTERN.fullmatch(value)
    if match is None:
        return None
    prefix, hour_text, minute_text = match[1], match[2], match[3]
    hour = _chinese_number(hour_text)
    if hour is None or hour > 23:
        return None
    minute = 30 if minute_text == "半" else (_chinese_number(minute_text) if minute_text else 0)
    if minute is None or minute > 59:
        return None
    periods = set(required_periods)
    if prefix in {"下午", "傍晚", "晚上", "中午"}:
        if 1 <= hour <= 11:
            hour += 12
    elif hour <= 6:
        if periods & {"afternoon", "evening", "after_work"}:
            hour += 12
        else:
            return None
    elif hour <= 11 and "evening" in periods:
        hour += 12
    try:
        return time(hour, minute)
    except ValueError:
        return None


def resolve_start_period_answers(previous_phase_a: dict[str, Any], answer_details: list[dict[str, Any]]) -> PhaseAResult | None:
    """Apply the UI's fixed time-period answers without asking the model to reinterpret them."""
    if not answer_details or any(detail["missing_field"] != "facts.start_time" for detail in answer_details):
        return None

    resolved = deepcopy(previous_phase_a)
    items_by_id = {item.get("item_id"): item for item in resolved.get("items", [])}
    answered_question_ids: set[str] = set()
    for detail in answer_details:
        item_ids = detail.get("covers_item_ids", [])
        if len(item_ids) != 1 or item_ids[0] not in items_by_id:
            return None
        item = items_by_id[item_ids[0]]
        choice = detail["answer"].strip()
        period = PERIOD_DEFAULT_START_TIMES.get(choice)
        if period is None:
            normalized_time = parse_time_answer(
                choice,
                required_periods=item.get("hard_constraints", {}).get("required_periods", []),
            )
            if normalized_time is None:
                return None
            normalized_time = normalized_time.strftime("%H:%M")
            required_period = None
            label = "用户填写的具体时间"
            source = "user_input"
        else:
            normalized_time, required_period, label = period
            source = "ai_assumption"

        item["facts"]["start_time"] = normalized_time
        item["hard_constraints"]["fixed_start_time"] = normalized_time
        if required_period and required_period not in item["hard_constraints"]["required_periods"]:
            item["hard_constraints"]["required_periods"].append(required_period)
        item["critical_missing"] = [field for field in item["critical_missing"] if field != "facts.start_time"]
        item["provenance"] = [entry for entry in item["provenance"] if entry.get("field_path") != "facts.start_time"]
        item["provenance"].append({
            "field_path": "facts.start_time",
            "value": normalized_time,
            "source": source,
            "reason": f"用户选择{label}；具体开始时间为{normalized_time}" if source == "ai_assumption" else "用户在追问中补充",
            "user_editable": source == "ai_assumption",
            "display_label": "AI猜测，可修改" if source == "ai_assumption" else "用户已确认",
        })
        answered_question_ids.add(detail["question_id"])

    resolved["questions"] = [
        question for question in resolved.get("questions", [])
        if question.get("question_id") not in answered_question_ids
    ]
    if resolved["questions"]:
        return None
    resolved["decision"] = PhaseADecision.READY.value
    resolved["manual_required"] = None
    normalize_before_event_deadlines(resolved, "Asia/Shanghai")
    return PhaseAResult.model_validate(resolved)


class PlanningOrchestrator:
    def __init__(self, repository, llm_service) -> None:
        self.repository = repository
        self.llm_service = llm_service

    def _record_run(
        self,
        *,
        session_id: str,
        stage: str,
        prompt_version: str,
        started: float,
        result: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        ModelRunRepository(self.repository.db).record(
            session_id=session_id,
            stage=stage,
            prompt_version=prompt_version,
            model=getattr(self.llm_service, "model_name", type(self.llm_service).__name__),
            request_id=None,
            validated_json=result.model_dump(mode="json") if result is not None else None,
            diagnostic_json=(
                {
                    "raw_model_output": error.raw_output,
                    "validation_errors": error.validation_errors,
                }
                if isinstance(error, ModelOutputValidationError)
                else None
            ),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            status="succeeded" if error is None else "failed",
            error_type=type(error).__name__ if error is not None else None,
        )

    def _persist_model_failure(self, session, error: Exception) -> None:
        if isinstance(error, (ValidationError, ModelOutputValidationError)):
            self.repository.update(session, status=PlanningStatus.VALIDATION_FAILED.value, error_code="MODEL_OUTPUT_INVALID")
        else:
            self.repository.update(session, status=PlanningStatus.MODEL_FAILED.value, error_code="MODEL_ERROR")

    async def submit(self, *, raw_input: str, reference_now: datetime, context: dict[str, Any]):
        session = self.repository.create(raw_input=raw_input, reference_now=reference_now)
        if not self.repository.claim_status(session.id, expected=PlanningStatus.RECEIVED.value, claimed=PlanningStatus.A_PROCESSING.value):
            raise InvalidStateTransition("planning session is already being processed")
        started = perf_counter()
        try:
            phase_a = await self.llm_service.run_phase_a({**context, "reference_now": reference_now.isoformat(), "user_input": raw_input})
        except Exception as exc:
            self._record_run(session_id=session.id, stage="a", prompt_version=PHASE_A_VERSION, started=started, error=exc)
            self._persist_model_failure(session, exc)
            raise
        self._record_run(session_id=session.id, stage="a", prompt_version=PHASE_A_VERSION, started=started, result=phase_a)
        status = {
            PhaseADecision.READY: PlanningStatus.A_READY,
            PhaseADecision.NEEDS_CLARIFICATION: PlanningStatus.NEEDS_CLARIFICATION,
            PhaseADecision.MANUAL_REQUIRED: PlanningStatus.MANUAL_REQUIRED,
            PhaseADecision.UNSUPPORTED: PlanningStatus.UNSUPPORTED,
        }[phase_a.decision]
        updated = self.repository.update(
            session,
            status=status.value,
            phase_a_json=phase_a.model_dump(mode="json"),
            prompt_a_version=PHASE_A_VERSION,
            error_code=None,
        )
        if phase_a.questions:
            self.repository.replace_questions(session.id, [
                {"question_id":q.question_id,"priority":q.priority,"missing_field":q.missing_field,"question":q.question}
                for q in phase_a.questions
            ])
        return updated

    async def answer(self, *, session_id: str, answers: dict[str, str], context: dict[str, Any]):
        session = self.repository.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status != PlanningStatus.NEEDS_CLARIFICATION.value:
            raise InvalidStateTransition(f"answer requires needs_clarification, got {session.status}")
        if not self.repository.claim_status(session.id, expected=PlanningStatus.NEEDS_CLARIFICATION.value, claimed=PlanningStatus.A_PROCESSING.value):
            raise InvalidStateTransition("planning session is already being processed")
        try:
            self.repository.save_answers(session_id, answers)
        except Exception:
            self.repository.update(session, status=PlanningStatus.NEEDS_CLARIFICATION.value)
            raise
        saved_answers = self.repository.get_answers(session_id)
        previous_phase_a = session.phase_a_json or {}
        questions_by_id = {
            question.get("question_id"): question
            for question in previous_phase_a.get("questions", [])
        }
        answer_details = []
        for question_id, answer in answers.items():
            question = questions_by_id.get(question_id, {})
            answer_details.append({
                "question_id": question_id,
                "answer": answer,
                "question": question.get("question", ""),
                "missing_field": question.get("missing_field", ""),
                "covers_item_ids": question.get("covers_item_ids", []),
            })
        deterministic_phase_a = resolve_start_period_answers(previous_phase_a, answer_details)
        if deterministic_phase_a is not None:
            updated = self.repository.update(
                session,
                status=PlanningStatus.A_READY.value,
                phase_a_json=deterministic_phase_a.model_dump(mode="json"),
                prompt_a_version=PHASE_A_VERSION,
                error_code=None,
            )
            self.repository.replace_questions(session.id, [], keep_answered=True)
            return updated
        payload = {
            **context,
            "reference_now": session.reference_now.isoformat(),
            "user_input": session.raw_input,
            "clarification_answers": saved_answers,
            "clarification_answer_details": answer_details,
            "previous_phase_a_result": previous_phase_a,
        }
        started = perf_counter()
        try:
            phase_a = await self.llm_service.run_phase_a(payload)
        except Exception as exc:
            self._record_run(session_id=session.id, stage="a", prompt_version=PHASE_A_VERSION, started=started, error=exc)
            self._persist_model_failure(session, exc)
            raise
        self._record_run(session_id=session.id, stage="a", prompt_version=PHASE_A_VERSION, started=started, result=phase_a)
        status = {
            PhaseADecision.READY: PlanningStatus.A_READY,
            PhaseADecision.NEEDS_CLARIFICATION: PlanningStatus.NEEDS_CLARIFICATION,
            PhaseADecision.MANUAL_REQUIRED: PlanningStatus.MANUAL_REQUIRED,
            PhaseADecision.UNSUPPORTED: PlanningStatus.UNSUPPORTED,
        }[phase_a.decision]
        updated = self.repository.update(session,status=status.value,phase_a_json=phase_a.model_dump(mode="json"),prompt_a_version=PHASE_A_VERSION,error_code=None)
        if phase_a.questions:
            self.repository.replace_questions(session.id, [{"question_id":q.question_id,"priority":q.priority,"missing_field":q.missing_field,"question":q.question} for q in phase_a.questions], keep_answered=True)
        return updated

    async def build_templates(self, *, session_id: str, context: dict[str, Any]):
        session = self.repository.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status != PlanningStatus.A_READY.value:
            raise InvalidStateTransition(f"build_templates requires a_ready, got {session.status}")
        if not self.repository.claim_status(session.id, expected=PlanningStatus.A_READY.value, claimed=PlanningStatus.B_PROCESSING.value):
            raise InvalidStateTransition("planning session is already being processed")
        phase_a = PhaseAResult.model_validate(session.phase_a_json)
        started = perf_counter()
        try:
            phase_b = await self.llm_service.run_phase_b(
                phase_a,
                {
                    **context,
                    "reference_now": session.reference_now.isoformat(),
                    "planning_window_days": planning_window_days(session.raw_input),
                },
            )
        except Exception as exc:
            self._record_run(session_id=session.id, stage="b", prompt_version=PHASE_B_VERSION, started=started, error=exc)
            self._persist_model_failure(session, exc)
            raise
        self._record_run(session_id=session.id, stage="b", prompt_version=PHASE_B_VERSION, started=started, result=phase_b)
        return self.repository.update(
            session,
            status=PlanningStatus.B_READY.value,
            phase_b_json=phase_b.model_dump(mode="json"),
            prompt_b_version=PHASE_B_VERSION,
            error_code=None,
        )
