# 测试记录

2026-09-23，macOS。Claude Code 2.1.280（Fable 5.1）；Codex CLI 0.156.1。Jev：`jev-latest`。

测试方法：用 tmux 驱动 TUI。先让 agent 分三次执行 `sleep 12`（每次一个工具调用），在第一次 sleep 期间发一条中途消息。

## 1. hook 能看到什么（Claude Code，影子模式）

| 中途消息 | `UserPromptSubmit` | Jev | 不干预时的原生行为 |
| --- | --- | --- | --- |
| 改一下，剩下的每次 sleep 3 就行 | 发送后立刻触发 | steer 0.99–1.0 | 下一个工具边界注入，后两次变成 sleep 3 |
| 做完这个任务之后，再告诉我当前目录下有几个文件 | 立刻触发 | queue 1.0 | 也被注入当前 turn，有一次和第三次 sleep 并行跑了 `ls` |
| 停一下，别继续了 | 立刻触发 | interrupt 1.0，explicit_stop 0.97–0.98 | 模型在当前工具结束后自己收尾 |
| （按 Esc） | 不触发任何 hook，也没有 Stop | — | 中断 |

- 中途消息的 `prompt_id` 等于当前 turn 的 `prompt_id`，新 turn 会拿到新的 `prompt_id`。
- Stop hook 触发续发期间再发的消息，同样带着原来的 `prompt_id`，被正确识别为中途消息。
- 通过 `continue:false` 硬停之后，不会触发 Stop hook。

## 2. 插件端到端（active 模式，`claude --plugin-dir ./claude-code`）

| 场景 | 插件动作 | 结果 |
| --- | --- | --- |
| queue | block → 入队 → Stop 用 `additionalContext` 续发 | 三次 sleep 全部完成后，显示 `Stop hook feedback`，然后才列目录 ✅ |
| steer | 放行 | 回复“收到，剩下两次改为 sleep 3”，后两次是 sleep 3 ✅ |
| interrupt | block → 下一个 PostToolUse 返回 `continue:false` | 第一次 sleep 结束后立即停止，没有多开一轮 ✅ |

早期版本的两个问题已修复：

- 用 `decision:block` 续发时，界面显示为 `Stop hook error`。改用 `additionalContext` 后显示为 `Stop hook feedback`。
- 放行“停一下”时，硬停之后它会自己开出一个新 turn。现在这条消息也会被 block。

## 3. Jev 延迟

共约 25 次调用，438–660ms，偶尔 1.5 秒左右。超时设为 3 秒时有 1 次超时；插件默认 2 秒，超时即放行。

## 4. Codex CLI

- 项目级 `.codex/hooks.json` 在信任目录下会加载；`SessionStart`、`UserPromptSubmit` 会触发，带 `turn_id`。
- 由于账号用量上限，模型没有跑起来，中途消息的行为还没测。

## 5. Codex CLI（2026-09-24，GPT-6-Luna low）

| 你做什么 | hook 是否触发 | 结果 |
| --- | --- | --- |
| Enter 插话（任务运行中） | `UserPromptSubmit` 立刻触发，`turn_id` = 当前 turn | 原生注入；加了提示后行为可控 |
| Tab 排队 | **不触发** | 消息等到本轮 Stop 之后才作为新 turn 出现；原生排队已经正确 |
| Esc | 触发 `Interrupt`（无 `turn_id`） | 正常中断 |
| 等待中的 turn | `Stop` 触发，带 `turn_id` | — |

关键结论：

- **在 Codex 里 block 会挂死本轮。** 对中途消息返回 `{"decision":"block"}` 后，没有新的模型调用，也没有 `Stop`，TUI 一直停在“Blocked by hook”，直到手动按 Esc。所以 Codex 适配器不 block，只加提示。
- **软提示有效。** queue 提示后，三次 sleep 全部按原计划做完，之后才列目录；stop 提示加 `PreToolUse` deny 后，第一次 sleep 结束就停了。延迟 760–980ms。
- **Codex 自己的提示词也会触发 `UserPromptSubmit`**（记忆整理、子会话、自动审查）。这些必须过滤，否则会把内部任务误当成“当前任务”。适配器用 `INTERNAL_MARKERS` 过滤。
- Codex hook 条目不能带插件配置，API key 走 `~/.jev-steer-or-queue/config.json`。

早期一次失败值得记下来：第一轮 e2e 测试时会话里没有 API key，路由静默走“失败即放行”，看起来像成功，实际只是 Codex 原生行为。日志里 `jev: null` 才能区分。
