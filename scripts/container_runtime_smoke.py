"""Container runtime smoke test — proves an image RUNS, per architecture.

Host-side driver (stdlib only): starts the built image against a real
PostgreSQL, applies migrations, and verifies the things a deployment depends
on — fail-closed boot, non-root user, dependency imports, LibreOffice and the
Times New Roman requirement that /readyz enforces, ClamAV client parsing,
HTTP health/release identity, worker startup, and a real DOCX render plus
PDF conversion inside the container. Emits machine-readable evidence.

A build that merely completed is not "verified" — this script is what turns
an image into runtime evidence, and it records the architecture it ran on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

IMPORTS = (
    "fastapi, sqlalchemy, asyncpg, pydantic, pydantic_settings, docx, "
    "defusedxml, boto3, httpx, alembic"
)


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _docker_exec(name: str, args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return _run(["docker", "exec", name] + args, timeout=timeout)


def _http_json(url: str, timeout: int = 10) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode())
        except Exception:
            return exc.code, {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--database-url", required=True,
                        help="asyncpg URL reachable FROM INSIDE the container")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--network", default="",
                        help="'host' on Linux CI; empty for port mapping")
    parser.add_argument("--port", type=int, default=18000)
    args = parser.parse_args()

    checks: list[dict] = []
    name = f"robofox-smoke-{int(time.time())}"
    uname = ""

    def record(check: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": check, "ok": bool(ok), "detail": detail[:400]})
        print(f"[{'PASS' if ok else 'FAIL'}] {check} {detail[:120]}")

    dev_env = [
        "-e", "ENV=development",
        "-e", f"DATABASE_URL={args.database_url}",
        "-e", "JWT_SECRET=" + "a" * 64,
        "-e", "ANTHROPIC_API_KEY=smoke-placeholder",
        "-e", "DEFAULT_INSTITUTION_SHORT_NAME=SMK",
        "-e", "MALWARE_SCAN_MODE=disabled",
        "-e", "PRODUCTION_REQUIRE_MALWARE_SCAN=false",
        "-e", "STORAGE_BACKEND=local",
        "-e", "AI_GLOBAL_ENABLED=false",
        "-e", "BILLING_PROVIDER=manual",
    ]

    # 1. Image identity and platform.
    insp = _run(["docker", "image", "inspect", args.image,
                 "--format", "{{.Architecture}}|{{.Os}}|{{.Id}}"])
    arch, os_name, image_id = (insp.stdout.strip() or "||").split("|")
    record("image_platform", insp.returncode == 0 and os_name == "linux",
           f"{os_name}/{arch} {image_id[:24]}")

    env_out = _run(["docker", "image", "inspect", args.image,
                    "--format", "{{range .Config.Env}}{{println .}}{{end}}"]).stdout
    baked = dict(line.split("=", 1) for line in env_out.splitlines() if "=" in line)
    record("release_identity_baked",
           baked.get("RELEASE_SHA") == args.expected_sha and bool(baked.get("BUILD_TIME")),
           f"RELEASE_SHA={baked.get('RELEASE_SHA', '')[:12]} BUILD_TIME={baked.get('BUILD_TIME', '')}")

    # 2. Fail-closed: production env with local storage must refuse to import.
    fc = _run(["docker", "run", "--rm",
               "-e", "ENV=production", "-e", "STORAGE_BACKEND=local",
               "-e", "DATABASE_URL=postgresql+asyncpg://x:x@db.invalid:5432/x?ssl=require",
               "-e", "JWT_SECRET=" + "a" * 64,
               "-e", "ANTHROPIC_API_KEY=smoke-placeholder",
               "-e", "RELEASE_SHA=" + "b" * 40,
               args.image, "python", "-c", "import app.main"], timeout=180)
    record("fail_closed_production_local_storage", fc.returncode != 0,
           f"rc={fc.returncode} (nonzero required)")

    # 3. Non-root.
    who = _run(["docker", "run", "--rm", args.image, "sh", "-c", "whoami; id -u"])
    record("non_root_user", who.stdout.split() == ["robofox", "10001"], who.stdout.strip())

    # 4. Dependency imports.
    imp = _run(["docker", "run", "--rm", args.image, "python", "-c",
                f"import {IMPORTS}; print('ok')"], timeout=180)
    record("python_dependency_imports", "ok" in imp.stdout, imp.stderr.strip()[-200:])

    # 5. LibreOffice + fonts (the /readyz pdf_stack requirements).
    lo = _run(["docker", "run", "--rm", args.image, "soffice", "--version"], timeout=180)
    record("libreoffice_binary", lo.returncode == 0, lo.stdout.strip()[:80])
    fonts = _run(["docker", "run", "--rm", args.image, "sh", "-c",
                  "fc-list | grep -ci 'times new roman'; fc-list | grep -ci liberation"])
    counts = fonts.stdout.split()
    record("fonts_times_new_roman_and_liberation",
           len(counts) == 2 and all(int(c) > 0 for c in counts),
           f"tnr={counts[0] if counts else '?'} liberation={counts[-1] if counts else '?'}")

    # 6. ClamAV client protocol handling.
    clam = _run(["docker", "run", "--rm", args.image, "python", "-c",
                 "from app.services.malware_service import _parse_clamd_response as p;"
                 "assert p('stream: OK\\x00').status=='clean'; print('ok')"])
    record("clamav_client_protocol", "ok" in clam.stdout, clam.stderr.strip()[-150:])

    # 7. Boot the app with a real database.
    net = ["--network", args.network] if args.network else ["-p", f"{args.port}:8000"]
    base = f"http://127.0.0.1:{8000 if args.network == 'host' else args.port}"
    started = _run(["docker", "run", "-d", "--name", name] + net + dev_env + [args.image])
    if started.returncode != 0:
        record("container_start", False, started.stderr.strip()[-200:])
    else:
        try:
            mig = _docker_exec(name, ["alembic", "upgrade", "head"], timeout=300)
            record("migrations_inside_container", mig.returncode == 0,
                   (mig.stderr or mig.stdout).strip().splitlines()[-1][:150] if (mig.stderr or mig.stdout).strip() else "")

            healthy = False
            for _ in range(45):
                try:
                    code, _body = _http_json(f"{base}/healthz")
                    if code == 200:
                        healthy = True
                        break
                except Exception:
                    pass
                time.sleep(2)
            record("healthz", healthy, base)

            code, release = _http_json(f"{base}/meta/release")
            record("meta_release_identity",
                   code == 200 and release.get("release_sha") == args.expected_sha,
                   json.dumps({k: release.get(k) for k in
                               ("release_sha", "schema_version", "renderer_version",
                                "canonical_schema_version", "prompt_bundle_version")}))

            code, ready = _http_json(f"{base}/readyz")
            comp = {k: v.get("ok") for k, v in ready.get("checks", {}).items()} if ready else {}
            record("readyz_components",
                   code == 200 and all(comp.get(k) for k in
                                       ("database", "migration", "pdf_stack", "storage")),
                   json.dumps(comp))

            # 8. Worker command startup (killed after it proves it loops).
            worker = _docker_exec(
                name, ["timeout", "8", "python", "-m", "app.services.job_queue"], timeout=60)
            record("worker_startup", worker.returncode in (0, 124),
                   f"rc={worker.returncode} (124 = looped until timeout)")

            # 9. Real DOCX render + LibreOffice PDF conversion inside the container.
            render = _docker_exec(name, ["python", "-c", (
                "from app.canonical.model import ThesisDocument, ChapterDoc, ParagraphBlock, Run\n"
                "from app.renderers.docx_renderer import render_docx\n"
                "from app.renderers.phase1_profiles import resolve_phase1_profile\n"
                "doc = ThesisDocument(chapters=[ChapterDoc(number=1, title='SMOKE', blocks=["
                "ParagraphBlock(runs=[Run(text='Synthetic smoke paragraph.')])])])\n"
                "profile, _ = resolve_phase1_profile('tn_university')\n"
                "path = '/tmp/robofox/smoke.docx'\n"
                "render_docx(doc, {}, profile, path)\n"
                "import hashlib; print(hashlib.sha256(open(path,'rb').read()).hexdigest())"
            )], timeout=300)
            docx_ok = render.returncode == 0 and len(render.stdout.strip()) == 64
            record("docx_render", docx_ok,
                   render.stdout.strip()[:64] if docx_ok else (render.stderr.strip()[-250:]))
            if docx_ok:
                pdf = _docker_exec(name, ["sh", "-c",
                                          "cd /tmp/robofox && soffice --headless --convert-to pdf "
                                          "smoke.docx >/dev/null 2>&1 && ls -la smoke.pdf | awk '{print $5}'"],
                                   timeout=300)
                size = pdf.stdout.strip()
                record("pdf_conversion", pdf.returncode == 0 and size.isdigit() and int(size) > 500,
                       f"pdf_bytes={size}")

            uname = _docker_exec(name, ["uname", "-m"]).stdout.strip()
        finally:
            _run(["docker", "rm", "-f", name])

    evidence = {
        "schema": "robofox.container-runtime-smoke.v1",
        "image": args.image,
        "image_id": image_id,
        "architecture_reported": arch,
        "container_uname_m": uname,
        "expected_release_sha": args.expected_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "passed": all(c["ok"] for c in checks),
    }
    with open(args.out, "w") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=True)
    print(f"\nsmoke {'PASSED' if evidence['passed'] else 'FAILED'} "
          f"({sum(c['ok'] for c in checks)}/{len(checks)}) -> {args.out}")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
