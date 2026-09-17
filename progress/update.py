#!/usr/bin/env python3
"""Update task status in plan.json, append to the log, and rebuild the dashboard.

Usage:
    python progress/update.py start P1.1 "note"
    python progress/update.py done  P1.1 "note"
    python progress/update.py todo  P1.1 "note"
    python progress/update.py note  P1   "free-form note attached to a phase"
    python progress/update.py risk  add "warning|info|critical" "title" "detail"
    python progress/update.py risk  clear R1
Add --tests to run pytest before rebuilding.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

PLAN = build.PLAN


def main(argv: list[str]) -> None:
    run_tests = "--tests" in argv
    argv = [a for a in argv if a != "--tests"]
    if len(argv) < 2:
        raise SystemExit(__doc__)
    plan = json.loads(PLAN.read_text())
    cmd, target = argv[0], argv[1]
    note = argv[2] if len(argv) > 2 else ""
    ts = datetime.now().astimezone().isoformat(timespec="seconds")

    if cmd == "risk":
        if target == "add":
            level, title, detail = argv[2], argv[3], argv[4] if len(argv) > 4 else ""
            rid = f"R{len(plan['risks']) + 1}"
            plan["risks"].append({"id": rid, "level": level, "title": title, "detail": detail})
        elif target == "clear":
            plan["risks"] = [r for r in plan["risks"] if r["id"] != argv[2]]
        else:
            raise SystemExit("risk add|clear")
    elif cmd == "note":
        plan["log"].append({"ts": ts, "phase": target, "task": None, "event": "note", "note": note})
    else:
        status = {"start": "doing", "done": "done", "todo": "todo"}[cmd]
        found = None
        for phase in plan["phases"]:
            for task in phase["tasks"]:
                if task["id"] == target:
                    task["status"] = status
                    found = phase
        if found is None:
            raise SystemExit(f"unknown task {target}")
        plan["log"].append({"ts": ts, "phase": found["id"], "task": target, "event": cmd, "note": note})

    PLAN.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    build.build(run_pytest=run_tests)


if __name__ == "__main__":
    main(sys.argv[1:])
