"""The production Uvicorn entry point must expose the tested application."""

from fastapi.testclient import TestClient

from app.blackbox_app import app as application
from app.main import app


def test_production_entrypoint_exposes_application():
    assert app is application
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
