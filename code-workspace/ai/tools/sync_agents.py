#!/usr/bin/env python3
"""Sync stock analysis agent definitions from source to Claude and Codex.

Reads Markdown source definitions from ai/agents/stock-analysis/ and generates:
  - .claude/agents/{name}.md  (Markdown, identical to source)
  - .codex/agents/{name}.toml (TOML, from frontmatter + body)
"""

import re
import sys
from pathlib import Path

ROOT = Path("/Users/fujie/code")
SOURCE_DIR = ROOT / "ai" / "agents" / "stock-analysis"
CLAUDE_DIR = ROOT / ".claude" / "agents"
CODEX_DIR = ROOT / ".codex" / "agents"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError(f"Missing frontmatter in source file")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed frontmatter")
    fm = parts[1]
    body = parts[2].lstrip()
    data: dict[str, str] = {}
    for line in fm.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip('"')
    return data, body


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_codex_agent(path: Path, meta: dict[str, str], body: str) -> None:
    lines = [
        "# Generated from /Users/fujie/code/ai/agents/stock-analysis.",
        "# Do not edit directly. Run: python3 /Users/fujie/code/ai/tools/sync_agents.py",
        "",
        f"name = {toml_string(meta['name'])}",
        f"description = {toml_string(meta.get('description', ''))}",
        'developer_instructions = """',
        body.rstrip().replace('"""', '\\"\\"\\"'),
        '"""',
        "",
    ]
    path.write_text("\n".join(lines))


def write_claude_agent(path: Path, source_text: str) -> None:
    header = "<!-- Generated from /Users/fujie/code/ai/agents/stock-analysis. Do not edit directly. -->\n"
    path.write_text(header + source_text)


def main() -> None:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    CODEX_DIR.mkdir(parents=True, exist_ok=True)

    sources = sorted(SOURCE_DIR.glob("*.md"))
    if not sources:
        print("ERROR: No source agent files found in", SOURCE_DIR, file=sys.stderr)
        sys.exit(1)

    for src in sources:
        text = src.read_text()
        meta, body = parse_frontmatter(text)
        name = meta["name"]
        (CLAUDE_DIR / f"{name}.md").write_text(text)
        write_claude_agent(CLAUDE_DIR / f"{name}.md", text)
        write_codex_agent(CODEX_DIR / f"{name}.toml", meta, body)
        print(f"  {name} -> .claude/agents/{name}.md, .codex/agents/{name}.toml")

    # Verify all generated TOML parses
    try:
        import tomllib
        for toml_file in sorted(CODEX_DIR.glob("*.toml")):
            tomllib.loads(toml_file.read_text())
    except ImportError:
        pass  # tomllib not available on older Python

    print(f"Synced {len(sources)} agents.")


if __name__ == "__main__":
    main()
