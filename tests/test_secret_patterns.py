from __future__ import annotations

from scripts.check_secret_patterns import scan_text


def _labels(value: str) -> set[str]:
    return {label for _line, label in scan_text(value)}


def test_secret_signatures_detect_credential_shapes_without_echoing_literals() -> None:
    assert _labels("token=" + "sk" + "-" + "a" * 24) == {"api_token"}
    assert _labels("key=" + "AK" + "IA" + "A" * 16) == {"aws_access_key"}
    assert _labels("-----" + "BEGIN " + "RSA PRIVATE KEY" + "-----") == {
        "private_key_header"
    }
    assert _labels("R2_SECRET_ACCESS_" + "KEY=actual-looking-value") == {
        "r2_secret_assignment"
    }


def test_placeholders_and_secret_references_are_allowed() -> None:
    text = "\n".join(
        [
            "ANTHROPIC_API_KEY=test-provider-key-placeholder",
            "R2_SECRET_ACCESS_" + "KEY=${R2_SECRET_ACCESS_KEY}",
            "R2_SECRET_ACCESS_" + "KEY=<injected-at-runtime>",
        ]
    )
    assert scan_text(text) == []
