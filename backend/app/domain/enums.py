from enum import StrEnum


class PhaseADecision(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    MANUAL_REQUIRED = "manual_required"
    UNSUPPORTED = "unsupported"


class PhaseBDecision(StrEnum):
    READY_FOR_SCHEDULING = "ready_for_scheduling"
    NEEDS_CLARIFICATION = "needs_clarification"
    MANUAL_REQUIRED = "manual_required"
    UNSUPPORTED = "unsupported"


class ItemKind(StrEnum):
    EXPLICIT_EVENT = "explicit_event"
    ABSTRACT_GOAL = "abstract_goal"
    SENSITIVE_GOAL = "sensitive_goal"
    UNSUPPORTED_EDIT_DELETE = "unsupported_edit_delete"
    IRRELEVANT = "irrelevant"


class ProvenanceSource(StrEnum):
    USER_INPUT = "user_input"
    USER_PROFILE = "user_profile"
    SYSTEM_DERIVED = "system_derived"
    AI_ASSUMPTION = "ai_assumption"
    AI_SUGGESTION = "ai_suggestion"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PlanningStatus(StrEnum):
    RECEIVED = "received"
    A_PROCESSING = "a_processing"
    NEEDS_CLARIFICATION = "needs_clarification"
    MANUAL_REQUIRED = "manual_required"
    UNSUPPORTED = "unsupported"
    A_READY = "a_ready"
    B_PROCESSING = "b_processing"
    B_READY = "b_ready"
    DRAFT_READY = "draft_ready"
    MODEL_FAILED = "model_failed"
    VALIDATION_FAILED = "validation_failed"


class DraftStatus(StrEnum):
    READY = "ready"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CalendarSource(StrEnum):
    AI = "ai"
    EXTERNAL = "external"
