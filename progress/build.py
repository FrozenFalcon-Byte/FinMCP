#!/usr/bin/env python3
"""Build the FinMCP progress dashboard.

Reads progress/plan.json, scans the repository for live vitals (lines of code,
test results, MCP surface, database counts, toolchain) and renders
progress/index.html from progress/template.html.

Usage:
    python progress/build.py            # rebuild page
    python progress/build.py --tests    # run pytest first, then rebuild
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "progress"
PLAN = PROGRESS / "plan.json"
TEMPLATE = PROGRESS / "template.html"
OUT = PROGRESS / "index.html"
JUNIT = PROGRESS / "junit.xml"

CODE_EXT = {".py", ".ts", ".tsx", ".css", ".sql", ".sh"}
SKIP_DIRS = {".venv", "node_modules", "dist", "build", "__pycache__", ".git", ".pytest_cache", "data"}

LAYERS = [
    ("MCP server", ["finmcp"], ["finmcp/ingestion"]),
    ("Ingestion", ["finmcp/ingestion"], []),
    ("Agent", ["agent"], []),
    ("Backend API", ["api"], []),
    ("Frontend", ["web/src"], []),
    ("Tests", ["tests"], []),
    ("Tooling", ["scripts", "progress"], []),
]


def count_lines(paths: list[str], exclude: list[str]) -> tuple[int, int]:
    files = 0
    lines = 0
    ex = [ROOT / e for e in exclude]
    for p in paths:
        base = ROOT / p
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            dp = Path(dirpath)
            if any(dp == e or e in dp.parents for e in ex):
                continue
            for fn in filenames:
                fp = dp / fn
                if fp.suffix in CODE_EXT:
                    try:
                        n = sum(1 for line in fp.open("r", encoding="utf-8", errors="ignore") if line.strip())
                    except OSError:
                        continue
                    files += 1
                    lines += n
    return files, lines


def loc_vitals() -> list[dict]:
    out = []
    for name, paths, exclude in LAYERS:
        files, lines = count_lines(paths, exclude)
        out.append({"layer": name, "files": files, "lines": lines})
    return out


def run_tests() -> None:
    py = ROOT / ".venv" / "bin" / "python"
    cmd = [str(py if py.exists() else sys.executable), "-m", "pytest", "-q", "--tb=short",
           "-p", "no:cacheprovider", f"--junitxml={JUNIT}", str(ROOT / "tests")]
    subprocess.run(cmd, cwd=ROOT, check=False)


def test_vitals() -> dict:
    res = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "duration": 0.0, "ran_at": None,
           "suites": []}
    if not JUNIT.exists():
        return res
    try:
        root = ET.parse(JUNIT).getroot()
    except ET.ParseError:
        return res
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    by_file: dict[str, dict] = {}
    for s in suites:
        res["total"] += int(s.get("tests", 0))
        res["failed"] += int(s.get("failures", 0))
        res["errors"] += int(s.get("errors", 0))
        res["skipped"] += int(s.get("skipped", 0))
        res["duration"] += float(s.get("time", 0))
        ts = s.get("timestamp")
        if ts:
            res["ran_at"] = ts
        for case in s.findall("testcase"):
            f = (case.get("classname") or "").split(".")[-1] or "tests"
            entry = by_file.setdefault(f, {"name": f, "passed": 0, "failed": 0, "skipped": 0})
            if case.find("failure") is not None or case.find("error") is not None:
                entry["failed"] += 1
            elif case.find("skipped") is not None:
                entry["skipped"] += 1
            else:
                entry["passed"] += 1
    res["passed"] = res["total"] - res["failed"] - res["errors"] - res["skipped"]
    res["suites"] = sorted(by_file.values(), key=lambda e: e["name"])
    return res


def mcp_vitals() -> dict:
    out = {"tools": [], "resources": [], "resource_templates": [], "prompts": [], "error": None}
    sys.path.insert(0, str(ROOT))
    try:
        os.environ.setdefault("FINMCP_DB", str(ROOT / "data" / "finmcp.db"))
        from finmcp.server import create_server  # type: ignore

        server = create_server()

        async def collect():
            tools = await server.list_tools()
            resources = await server.list_resources()
            templates = await server.list_resource_templates()
            prompts = await server.list_prompts()
            return (
                [t.name for t in tools],
                [str(r.uri) for r in resources],
                [t.uriTemplate for t in templates],
                [p.name for p in prompts],
            )

        tools, resources, templates, prompts = asyncio.run(collect())
        out.update({"tools": tools, "resources": resources, "resource_templates": templates, "prompts": prompts})
    except Exception as exc:  # server not built yet, or import error
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def db_vitals() -> dict:
    import sqlite3

    path = Path(os.environ.get("FINMCP_DB", ROOT / "data" / "finmcp.db"))
    out = {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
           "exists": path.exists(), "transactions": 0, "categories": 0, "uncategorized": 0,
           "first_date": None, "last_date": None, "tables": []}
    if not path.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = con.cursor()
        out["tables"] = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        if "transactions" in out["tables"]:
            out["transactions"] = cur.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            out["uncategorized"] = cur.execute("SELECT COUNT(*) FROM transactions WHERE category_id IS NULL").fetchone()[0]
            row = cur.execute("SELECT MIN(date), MAX(date) FROM transactions").fetchone()
            out["first_date"], out["last_date"] = row
        if "categories" in out["tables"]:
            out["categories"] = cur.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        con.close()
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    return out


def toolchain_vitals() -> list[dict]:
    def ver(cmd: list[str]) -> str | None:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except Exception:
            return None

    py = ROOT / ".venv" / "bin" / "python"
    items = [
        {"name": "Python", "value": ver([str(py if py.exists() else sys.executable), "--version"]) or "missing"},
        {"name": "Node", "value": ver(["node", "--version"]) or "missing"},
        {"name": "npm", "value": ver(["npm", "--version"]) or "missing"},
        {"name": "Tesseract", "value": (ver(["tesseract", "--version"]) or "missing").replace("tesseract ", "")},
        {"name": "SQLite", "value": ver(["sqlite3", "--version"]) or "missing"},
        {"name": "Git", "value": ver(["git", "--version"]) or "missing"},
    ]
    for it in items:
        it["ok"] = it["value"] != "missing"
        if it["ok"]:
            it["value"] = it["value"].replace("Python ", "").replace("git version ", "").split(" ")[0]

    # Package presence
    def pkg(name: str) -> str:
        try:
            r = subprocess.run([str(py), "-c", f"import importlib.metadata as m;print(m.version('{name}'))"],
                               capture_output=True, text=True, timeout=20)
            return r.stdout.strip() or "missing"
        except Exception:
            return "missing"

    for name in ("mcp", "anthropic", "fastapi", "pdfplumber", "pytesseract"):
        v = pkg(name) if py.exists() else "missing"
        items.append({"name": name, "value": v, "ok": v != "missing"})

    # API key presence (never the value)
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    env_file = ROOT / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY=") and len(line.split("=", 1)[1].strip()) > 10:
                key = True
    items.append({"name": "ANTHROPIC_API_KEY", "value": "set" if key else "not set", "ok": key})
    node_modules = (ROOT / "web" / "node_modules").exists()
    items.append({"name": "web/node_modules", "value": "installed" if node_modules else "not yet", "ok": node_modules})
    return items


def git_vitals() -> dict:
    out = {"repo": False, "commits": 0, "last": None, "dirty": 0}
    if not (ROOT / ".git").exists():
        return out
    out["repo"] = True
    try:
        out["commits"] = int(subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or 0)
        out["last"] = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
        out["dirty"] = len([l for l in subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines() if l.strip()])
    except Exception:
        pass
    return out


def build(run_pytest: bool = False) -> Path:
    if run_pytest:
        run_tests()
    plan = json.loads(PLAN.read_text())
    now = datetime.now().astimezone()
    vitals = {
        "generated_at": now.isoformat(timespec="seconds"),
        "loc": loc_vitals(),
        "tests": test_vitals(),
        "mcp": mcp_vitals(),
        "db": db_vitals(),
        "toolchain": toolchain_vitals(),
        "git": git_vitals(),
    }
    payload = json.dumps({"plan": plan, "vitals": vitals}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    html = TEMPLATE.read_text()
    marker = "/*__DATA__*/{}"
    if marker not in html:
        raise SystemExit("template.html is missing the /*__DATA__*/{} marker")
    OUT.write_text(html.replace(marker, payload))
    total = sum(len(p["tasks"]) for p in plan["phases"])
    done = sum(1 for p in plan["phases"] for t in p["tasks"] if t["status"] == "done")
    print(f"progress/index.html written · {done}/{total} tasks done · {sum(l['lines'] for l in vitals['loc'])} lines · "
          f"tests {vitals['tests']['passed']}/{vitals['tests']['total']} · tools {len(vitals['mcp']['tools'])}")
    return OUT


if __name__ == "__main__":
    build(run_pytest="--tests" in sys.argv)
