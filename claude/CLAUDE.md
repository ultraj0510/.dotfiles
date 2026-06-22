<!-- User customizations -->
# 個人の作業スタイル

## 言語
- 返答は日本語で
- コミットメッセージ・コードコメントは英語で

## 姿勢
- 実装前に自己ダメ出しをして提案を見直す
- 計画が必要な作業はEnterPlanModeで合意を取ってから実装する
- セキュリティ（XSS, SQLi, コマンドインジェクション等）を常に意識する

## コーディング規則
- 聞かれていない改善・リファクタリングはしない
- 不要なコメント・docstring・型アノテーションは追加しない
- 1回限りの処理に抽象化・ユーティリティ関数を作らない
- 後方互換ハックは入れない（使われていないものは削除する）

## コミュニケーション
- 長い前置きや要約は省く
- ファイル参照は `path:line` 形式で示す
- 絵文字は使わない（明示的に求められた場合を除く）

---

## Workflow Orchestration

### 1. Plan Node Default

- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy

- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop

- After ANY correction from the user: update `/Users/fujie/code/docs/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done

- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)

- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing

- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write durable plans to `/Users/fujie/code/docs/plans/` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Update the active plan file as work progresses
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review notes to the active plan file
6. **Capture Lessons**: Update `/Users/fujie/code/docs/lessons.md` after corrections

---

## Core Principles

**Simplicity First**: Make every change as simple as possible. Impact minimal code.
**No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
**Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
