"""Detect (names only) whether required staging secrets exist in GitHub.

Never prints, fetches or stores secret values — the GitHub API only exposes
names and timestamps for Actions secrets. Exit 0 when everything required for
a staging dispatch of phase5-release.yml is present, 1 otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "febufenn-cyber/thesis-studio-backend"
ENVIRONMENT_SECRETS = [
    "STAGING_HOST",
    "STAGING_USER",
    "STAGING_SSH_KEY",
    "STAGING_ENV_PATH",
    "STAGING_DEPLOY_PATH",
    "STAGING_BASE_URL",
    "CLAMAV_IMAGE",
]
REPO_SECRETS = ["RELEASE_VALIDATION_DATABASE_URL"]


def _names(endpoint: str) -> set[str]:
    """Return the secret names at a GitHub API endpoint (names only)."""
    proc = subprocess.run(
        ["gh", "api", endpoint, "--jq", "[.secrets[].name]"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"error: gh api {endpoint} failed: {proc.stderr.strip()[:200]}")
        return set()
    return set(json.loads(proc.stdout or "[]"))


def main() -> int:
    env_present = _names(f"repos/{REPO}/environments/staging/secrets")
    repo_present = _names(f"repos/{REPO}/actions/secrets")
    missing = 0
    print("scope        secret                              present")
    print("-" * 60)
    for name in ENVIRONMENT_SECRETS:
        ok = name in env_present
        missing += 0 if ok else 1
        print(f"staging-env  {name:<35} {'yes' if ok else 'MISSING'}")
    for name in REPO_SECRETS:
        ok = name in repo_present
        missing += 0 if ok else 1
        print(f"repository   {name:<35} {'yes' if ok else 'MISSING'}")
    print("-" * 60)
    print(f"missing: {missing}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
