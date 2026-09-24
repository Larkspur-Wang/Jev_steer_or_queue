<div align="center">

<img src="assets/banner.svg" alt="Jev steer or queue" width="100%">

<br>

**Your coding agent is busy. You send another message. Should it change course, wait its turn, or stop?**<br>
A hook that lets [TypeSafe Jev](https://docs.typesafe.ai/) make that call in about half a second.

<br>

[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757?style=flat-square&logo=claude&logoColor=white)](claude-code/)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-supported%20(soft)-10a37f?style=flat-square)](codex/)
[![Powered by Jev](https://img.shields.io/badge/powered%20by-TypeSafe%20Jev-7c5cff?style=flat-square)](https://docs.typesafe.ai/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)](claude-code/scripts/jev_router.py)
[![Dependencies](https://img.shields.io/badge/dependencies-none-0ea5e9?style=flat-square)](claude-code/scripts/jev_router.py)
<br>
[![GitHub stars](https://img.shields.io/github/stars/Larkspur-Wang/Jev_steer_or_queue?style=flat-square&logo=github)](https://github.com/Larkspur-Wang/Jev_steer_or_queue/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/Larkspur-Wang/Jev_steer_or_queue?style=flat-square)](https://github.com/Larkspur-Wang/Jev_steer_or_queue/commits/main)
[![Issues](https://img.shields.io/github/issues/Larkspur-Wang/Jev_steer_or_queue?style=flat-square)](https://github.com/Larkspur-Wang/Jev_steer_or_queue/issues)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-ff69b4?style=flat-square)](#contributing)

**English** · [简体中文](README.zh-CN.md)

</div>

---

## Why

Coding agents treat every message you send mid-turn the same way. Claude Code injects it into the running turn right away. That works for *"use the simpler approach"*, but not for *"when you're done, update the changelog"*, which then gets mixed into the current task. Nor does it work for *"stop, don't continue"*, which only works if the model decides to stop.

This project classifies each mid-turn message into one of three timings and acts on it:

| Jev says | Meaning | What the hook does |
| :--- | :--- | :--- |
| 🟢 **steer** | Change the running task now | Lets it through; the client injects it at the next tool boundary |
| 🟡 **queue** | Separate request, do it afterwards | Holds it in a per-session FIFO and replays it when the turn ends |
| 🔴 **interrupt** | Stop the running task | Swallows the message and ends the turn at the next tool boundary |

Messages sent while the agent is idle are never touched and never sent to Jev.

## Clients

| Client | Folder | Status |
| :--- | :--- | :--- |
| Claude Code CLI | [`claude-code/`](claude-code/) | ✅ Tested end to end on 2.1.280 |
| Codex CLI | [`codex/`](codex/) | ✅ Tested on 0.156.1, with a caveat: Codex can only be nudged, not blocked |

The two clients have different hook contracts, so each one has its own self-contained folder.

## How it works

```mermaid
flowchart LR
    U([You type while<br/>the agent works]) --> H{{UserPromptSubmit hook}}
    H -- idle --> P[Pass through]
    H -- mid-turn --> J[Jev<br/>~0.5 s]
    J -- steer --> S[Allow:<br/>native injection]
    J -- queue --> Q[Block + FIFO] --> ST[Stop hook replays it<br/>after the turn]
    J -- interrupt --> I[Block + flag] --> T[Next tool hook:<br/>continue:false]
    J -- unsure / error / timeout --> S
```

- **Mid-turn detection:** Claude Code gives a mid-turn message the running turn's `prompt_id`, and gives a new turn a fresh one.
- **Only confident answers change behaviour.** Queue and interrupt each need probability ≥ 0.9, and interrupt also needs an explicit "stop" signal. Anything else falls back to the client's native behaviour.
- **Fails open.** A missing key, a network error or a timeout (default 2 s) means the message passes through untouched.

## Quick start (Claude Code)

```text
/plugin marketplace add Larkspur-Wang/Jev_steer_or_queue
/plugin install jev-steer-or-queue@jev-steer-or-queue
```

Claude Code then asks for:

1. **TypeSafe API key.** Get one at [console.typesafe.ai](https://console.typesafe.ai/). It is stored in the system keychain. Leave it empty to use the `TYPESAFE_API_KEY` environment variable.
2. **Mode.** `shadow` (the default) only logs decisions. `active` queues and stops for real. You can change it later in `/config`.

Start in `shadow`, read the log for a few days, then switch to `active`. See [`claude-code/README.md`](claude-code/README.md) for all options.

## Limitations

- **The hook can only stop at tool boundaries.** A running command finishes first, and a turn that is only producing text can't be stopped.
- **Esc fires no hook.** Messages still in the queue when you press Esc are listed and dropped on your next prompt.
- **Held messages don't appear as user messages.** You see the hook's notice, and a replayed message shows up as `Stop hook feedback`.
- **Jev can be wrong,** especially on colloquial Chinese, negations and messages with several intents. Calibrate the thresholds on your own messages.

## Privacy

For every **mid-turn** message, the hook sends TypeSafe the message (up to 2,000 characters) and the start of the current task (up to 500 characters). Nothing else is sent: no transcript, no files, no tool output. Logs stay on your machine; set `JEV_ROUTER_LOG_PROMPTS=false` to keep message text out of them.

## Test results

See [`docs/test-results.md`](docs/test-results.md) for the Chinese-language test notes: what each hook actually receives, how the client behaves with and without the plugin, and latency.

## Contributing

Issues and pull requests are welcome, especially:

- real mid-turn messages that were misclassified (redact them first),
- Codex CLI test results,
- adapters for other clients (Cursor, Grok Build, OpenClaw).

## Acknowledgements

- [TypeSafe](https://typesafe.ai/) for Jev and the System One API.
- The OpenClaw [queue modes](https://docs.openclaw.ai/concepts/queue) (`steer` / `followup` / `interrupt`) and other Jev-based routers ([pi-card](https://github.com/carbon-ni/pi-card), [KiroCrew #12338](https://github.com/kirodotdev/KiroCrew/pull/12338)) for prior art.

## License

[MIT](LICENSE) © 2026 Larkspur-Wang. Not affiliated with TypeSafe, Anthropic or OpenAI.
