# Codex 关键任务收尾检查

## 注册 Hook

在支持 Hook 的本机 Codex 中使用。先通过 `install.sh` 建立全局 `AGENTS.md` 链接。以下路径适用于把本仓库置于 `~/.dotfiles` 的 Mac。

将以下两组处理器分别追加到 `~/.codex/hooks.json` 的 `hooks` 对象。已有同一脚本的处理器时沿用原条目。保留现有处理器及其顺序。文件不存在时可直接使用下面的 JSON。

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 \"$HOME/.dotfiles/agent-guidance/hooks/critical-task.py\" hook",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 \"$HOME/.dotfiles/agent-guidance/hooks/critical-task.py\" hook",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

在本机 Codex 的 `/hooks` 检查两个处理器的命令，逐条信任。用新会话核对实际加载。隔离测试可用 `/usr/bin/python3 -B "$HOME/.dotfiles/agent-guidance/hooks/test_critical_task.py"` 执行。

## 使用与验收

在全局规约规定的关键行动任务中，从当前 Codex 会话登记一次。`CODEX_SESSION_ID` 将记录绑定到该会话。开工时确认用户关心的实际结果、授权范围和目标系统的证据。硬时限已知时，记录最后可补救时间和最终截止时间。时间必须带时区。

```sh
guard="$HOME/.dotfiles/agent-guidance/hooks/critical-task.py"
/usr/bin/python3 "$guard" start --outcome '两款商品各一件已进入官方购物车' \
  --scope '经用户授权只加购物车，付款由用户完成' \
  --acceptance '官方购物车读到两款指定商品各一件' \
  --recover-by '2030-01-15T11:57:00+09:00' --deadline '2030-01-15T12:00:00+09:00'
/usr/bin/python3 "$guard" status
```

示例时间用于演练。按本次实际情况确定最晚可补救时间。尚无法确定时，说明缺少什么证据。收到用户调整或查到新的时限时，用 `revise --reason '<指令或证据>'` 更新当前任务的相关字段。原任务仍是开放状态。登记后的任务可在四种状态下结束当前回合。

- `verified` 记录目标系统的结果证据。用实际记录、回读或独立验收作依据。有硬时限时，用 `--occurred-at` 记录目标实际达成的带时区时间。可以事后回读按时达成的记录。脚本启动或日志无错误只证明相应阶段。
- `handed-off` 记录已开始负责的接手方、下一次核对时间、实际接收证据、以及故障演练证据。看到进程启动后还要验证谁能在需要时收到提醒并行动。对硬时限任务，要先确定早于截止的可补救时点。交接检查时间不得晚于该时点。把实际结果继续标为待验证。
- `blocked` 记录真实的外部缺口、已核查事实、对当前结果的影响。还能取得证据或安全补救时继续工作。
- `stopped` 引用用户明确暂停、取消或缩小范围的指令。仅完成新的授权范围。当前回合追问进度时保留原任务责任，直至用户明确调整目标。

用 `close --as <状态> --evidence '<证据引用>'` 登记。交接再提供 `--owner '<接手方>' --next-check '<带时区的时间>' --ack '<接收证据>' --drill '<故障演练证据>'`。证据只写可复核引用和必要状态。保留原有项目验收记录，在这里引用即可。

Codex 在明确的高风险措辞出现时提醒核对范围。Agent 负责登记符合条件的行动任务。全局 Stop Hook 会在登记任务仍开放时要求复查一次。若用户只要求读进度，核实本轮授权后如实报告，保留原任务状态。遇到真正阻塞时，及时告知用户。Hook 校验记录和时限，目标系统与接收方仍须实际核验。会话状态存在本机私有临时目录。跨重启或无人值守的执行与报警需要独立的实际承接，不能靠该记录维持运行。

用 `/hooks` 查看本机 Hook。若需撤回，只停用本任务的两个处理器。保留其他 Hook 与既有任务记录。
