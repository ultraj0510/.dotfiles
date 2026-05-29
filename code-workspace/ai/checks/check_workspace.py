#!/usr/bin/env python3
"""Workspace hygiene checker. Validates structure matches workspace.toml."""
import sys
import tomllib
from pathlib import Path

ROOT = Path("/Users/fujie/code")
MANIFEST = ROOT / "workspace.toml"

FORBIDDEN_NAMES = {".DS_Store", "__pycache__", ".pytest_cache"}
FORBIDDEN_SOURCE_STATE = {
    ROOT / "ai" / "agents" / "stock-analysis" / ".omc",
}
REQUIRED_PATHS = [
    ROOT / "workspace.md",
    ROOT / "workspace.toml",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "ai" / "agents" / "stock-analysis",
    ROOT / "ai" / "tools" / "sync_agents.py",
    ROOT / "docs" / "plans",
    ROOT / "docs" / "lessons.md",
    ROOT / "runtime",
    ROOT / "scratch",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not MANIFEST.exists():
        fail(f"missing {MANIFEST}")

    data = tomllib.loads(MANIFEST.read_text())
    if data["workspace"]["root"] != str(ROOT):
        fail("workspace.root does not match /Users/fujie/code")

    for path in REQUIRED_PATHS:
        if not path.exists():
            fail(f"missing required path: {path}")

    for path in FORBIDDEN_SOURCE_STATE:
        if path.exists():
            fail(f"runtime state under source tree: {path}")

    bad = []
    for path in ROOT.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            bad.append(path)
    if bad:
        for path in bad:
            print(f"FORBIDDEN: {path}", file=sys.stderr)
        fail("forbidden generated files exist")

    print("workspace hygiene ok")


if __name__ == "__main__":
    main()
