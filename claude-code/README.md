# Claude Code plugin · `jev-steer-or-queue`

[← Back to the project README](../README.md)

This plugin routes messages you send while Claude Code is running a task. It uses five hooks: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` and `StopFailure`. The hook script is a single [`scripts/jev_router.py`](scripts/jev_router.py) with no dependencies beyond Python's standard library.

| Jev says | Plugin action | What you see |
| :--- | :--- | :--- |
| 🟢 steer | allow; Claude Code injects the message natively | nothing changes |
| 🟡 queue | block, add to a per-session FIFO, replay from the Stop hook | `已排队（Jev queue 0.99）…`, then `Stop hook feedback: …` once the turn ends |
| 🔴 interrupt | block, then `continue:false` at the next tool hook | `PostToolUse:Bash hook stopped continuation: …` |

## Requirements

- Claude Code **2.1.196 or later**, for the `prompt_id` hook field. Tested on 2.1.280.
- `python3` 3.8 or later on your `PATH`.
- A TypeSafe API key from [console.typesafe.ai](https://console.typesafe.ai/).

## Install

```text
/plugin marketplace add Larkspur-Wang/Jev_steer_or_queue
/plugin install jev-steer-or-queue@jev-steer-or-queue
```

Or non-interactively, from a shell:

```bash
claude plugin marketplace add Larkspur-Wang/Jev_steer_or_queue
claude plugin install jev-steer-or-queue@jev-steer-or-queue --config mode=shadow
```

Leave the key empty to read `TYPESAFE_API_KEY` from the environment, or set it with `/plugin` so it is stored in the keychain.

To try it for one session without installing anything:

```bash
TYPESAFE_API_KEY=sk-... JEV_ROUTER_MODE=active claude --plugin-dir ./claude-code
```

## Configuration

Environment variables override the plugin options.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `JEV_ROUTER_MODE` | `shadow` | `shadow` only logs; `active` queues and stops |
| `TYPESAFE_API_KEY` | — | Used when the plugin option is empty |
| `JEV_ROUTER_QUEUE_THRESHOLD` | `0.9` | Minimum `queue` probability to hold a message |
| `JEV_ROUTER_INTERRUPT_THRESHOLD` | `0.9` | Minimum `interrupt` probability, and minimum explicit-stop score, to stop |
| `JEV_ROUTER_TIMEOUT_S` | `2.0` | Jev request timeout; on timeout the message passes through |
| `JEV_ROUTER_JEV_MODEL` | `jev-latest` | TypeSafe model id |
| `JEV_ROUTER_TYPESAFE_API_URL` | `https://api.typesafe.ai/v1/systemone` | API endpoint |
| `JEV_ROUTER_LOG_PROMPTS` | `true` | `false` keeps message text out of the log |

## Logs and state

Everything is stored under the plugin data directory, `~/.claude/plugins/data/jev-steer-or-queue-jev-steer-or-queue/`:

- `log.jsonl` has one line per decision: probabilities, latency and the action taken.
- `sessions/` holds per-session state and queues.

To review shadow-mode decisions:

```bash
jq -c 'select(.mid_turn) | {prompt, choice: .jev.choice, p: .jev.probabilities, ms: .jev.ms}' \
  ~/.claude/plugins/data/jev-steer-or-queue-jev-steer-or-queue/log.jsonl
```

## Known limitations

- The plugin can only stop at a tool boundary. A running command finishes first, and a turn that is only producing text can't be stopped.
- Esc fires no hook. When you press Esc, anything still queued is listed and dropped on your next prompt.
- Held messages are erased from the transcript. A replayed message arrives as `Stop hook feedback`, not as a user message.
- Claude Code caps consecutive Stop-hook continuations at 8.
- Each mid-turn message waits for Jev, usually 450–650 ms.
