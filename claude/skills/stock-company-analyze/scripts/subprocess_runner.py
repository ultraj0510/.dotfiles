"""Subprocess runner with skill path registry."""
import json
import subprocess
from dataclasses import dataclass


SKILL_PATHS = {
    "stock-info-fetch": "/Users/fujie/.dotfiles/claude/skills/stock-info-fetch/scripts/fetch_stock_info",
    "stock-price-fetch": "/Users/fujie/.dotfiles/claude/skills/stock-price-fetch/scripts/fetch_stock_price",
    "stock-ir-fetch": "/Users/fujie/.dotfiles/claude/skills/stock-ir-fetch/scripts/fetch_stock_ir",
}


@dataclass
class SkillResult:
    skill_name: str
    args: list[str]
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False

    @property
    def parsed(self) -> dict | None:
        try:
            return json.loads(self.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_skill(skill_name: str, args: list[str], timeout: int = 300) -> SkillResult:
    if skill_name not in SKILL_PATHS:
        raise ValueError(f"Unknown skill: {skill_name}")
    exe = SKILL_PATHS[skill_name]
    cmd = [exe, *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=False,
        )
        return SkillResult(
            skill_name=skill_name, args=args,
            stdout=proc.stdout, stderr=proc.stderr,
            exit_code=proc.returncode, timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(skill_name=skill_name, args=args, timed_out=True)
