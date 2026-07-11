#!/usr/bin/env python3
"""Read-only post-deploy smoke test for Phase 5 releases."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch_json(base: str, path: str, timeout: float) -> tuple[int, dict]:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        headers={"User-Agent": "robofox-phase5-smoke/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:1000]}
        return exc.code, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    checks: list[dict] = []
    failures: list[str] = []
    for path, allowed in (("/healthz", {200}), ("/readyz", {200}), ("/status", {200}), ("/meta/release", {200})):
        status, payload = fetch_json(args.base_url, path, args.timeout)
        checks.append({"path": path, "status": status, "payload": payload})
        if status not in allowed:
            failures.append(f"{path} returned {status}")

    release = next((row["payload"] for row in checks if row["path"] == "/meta/release"), {})
    health = next((row["payload"] for row in checks if row["path"] == "/healthz"), {})
    status_page = next((row["payload"] for row in checks if row["path"] == "/status"), {})
    if release.get("release_sha") != args.expected_release:
        failures.append(
            f"release mismatch: expected {args.expected_release}, received {release.get('release_sha')}"
        )
    if health.get("phase") != "commercial_reliability_security_scale":
        failures.append("health endpoint is not reporting Phase 5")
    component_keys = {row.get("key") for row in status_page.get("components", [])}
    expected_components = {"web", "auth", "editing", "ai", "ingestion", "pdf", "downloads", "email"}
    missing = sorted(expected_components - component_keys)
    if missing:
        failures.append(f"status page is missing components: {', '.join(missing)}")
    if not status_page.get("ai_reported_separately"):
        failures.append("status page does not separate AI availability")

    result = {"ok": not failures, "failures": failures, "checks": checks}
    print(json.dumps(result, indent=2, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
