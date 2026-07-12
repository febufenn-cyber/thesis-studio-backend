"""Release-candidate safety checks that do not require external infrastructure."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from pydantic import ValidationError

from app.core.config import Settings
from app.ingest.preflight import inspect_docx
from app.main import app
from app.services.malware_service import (
    MalwareDetectedError,
    MalwareScannerUnavailableError,
    _parse_clamd_response,
)


def _settings(**overrides):
    values = {
        "ENV": "development",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/test",
        "JWT_SECRET": "x" * 64,
        "ANTHROPIC_API_KEY": "test-placeholder-key",
        "STORAGE_BACKEND": "local",
        "PRODUCTION_REQUIRE_R2": False,
        "PRODUCTION_REQUIRE_MALWARE_SCAN": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_clamd_clean_response() -> None:
    result = _parse_clamd_response("stream: OK\x00")
    assert result.status == "clean"
    assert result.engine == "clamav"


def test_clamd_detected_response_is_rejected() -> None:
    with pytest.raises(MalwareDetectedError):
        _parse_clamd_response("stream: Eicar-Test-Signature FOUND\x00")


def test_clamd_error_and_unknown_response_fail_closed() -> None:
    with pytest.raises(MalwareScannerUnavailableError):
        _parse_clamd_response("stream: temporary failure ERROR\x00")
    with pytest.raises(MalwareScannerUnavailableError):
        _parse_clamd_response("unexpected")


def test_production_requires_clamav() -> None:
    with pytest.raises(ValidationError, match="MALWARE_SCAN_MODE=clamav"):
        _settings(
            ENV="production",
            RELEASE_SHA="a" * 40,
            STORAGE_BACKEND="r2",
            PRODUCTION_REQUIRE_R2=True,
            R2_ACCOUNT_ID="account",
            R2_ACCESS_KEY_ID="access",
            R2_SECRET_ACCESS_KEY="secret",
            R2_BUCKET_NAME="bucket",
            PRODUCTION_REQUIRE_MALWARE_SCAN=True,
            MALWARE_SCAN_MODE="disabled",
        )


def test_production_accepts_configured_clamav() -> None:
    settings = _settings(
        ENV="production",
        RELEASE_SHA="a" * 40,
        STORAGE_BACKEND="r2",
        PRODUCTION_REQUIRE_R2=True,
        R2_ACCOUNT_ID="account",
        R2_ACCESS_KEY_ID="access",
        R2_SECRET_ACCESS_KEY="secret",
        R2_BUCKET_NAME="bucket",
        PRODUCTION_REQUIRE_MALWARE_SCAN=True,
        MALWARE_SCAN_MODE="clamav",
        CLAMAV_HOST="clamav.internal",
    )
    assert settings.MALWARE_SCAN_MODE == "clamav"


def test_docx_preflight_records_nonproduction_scan_state(tmp_path: Path) -> None:
    path = tmp_path / "clean.docx"
    document = Document()
    document.add_paragraph("CHAPTER I")
    document.save(path)

    report = inspect_docx(str(path))
    assert report.package["malware_scan"] == {
        "status": "skipped",
        "engine": "disabled",
    }


def test_every_merged_control_plane_router_is_reachable() -> None:
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    required = {
        ("/institutions/{institution_id}/policies/{policy_id}/state", "POST"),
        ("/projects/{project_id}/shared-sources", "GET"),
        ("/institutions/{institution_id}/reliability/dashboard", "GET"),
        ("/status", "GET"),
        ("/meta/release", "GET"),
    }
    assert required <= routes
