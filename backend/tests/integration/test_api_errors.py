from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.client import LLMRequestError
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine


class FailingLLMService:
    async def run_phase_a(self, context):
        raise LLMRequestError("模型网关连接失败")


def make_client(service=None):
    engine=create_sqlite_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(engine)
    return TestClient(create_app(settings=Settings(),session_factory=create_session_factory(engine),llm_service=service or FailingLLMService()),raise_server_exceptions=False)


def test_validation_error_uses_unified_error_shape_and_request_id() -> None:
    response = make_client().post("/api/planning/sessions", json={"raw_input":""})

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["retryable"] is False
    assert response.headers["X-Request-ID"]


def test_model_failure_returns_retryable_503() -> None:
    response = make_client().post("/api/planning/sessions", json={"raw_input":"开会"})

    assert response.status_code == 503
    assert response.json()["error_code"] == "MODEL_UNAVAILABLE"
    assert response.json()["retryable"] is True
