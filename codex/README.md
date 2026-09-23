# Codex CLI · in testing 🧪

[← Back to the project README](../README.md)

The Codex CLI adapter is not released yet.

## What we know

From the [Codex hooks docs](https://learn.chatgpt.com/docs/hooks) and a first probe on Codex CLI 0.156.1:

| Need | Codex hook | Status |
| :--- | :--- | :--- |
| See a mid-turn message | `UserPromptSubmit` (carries `turn_id`) | Fires on submit ✅; mid-turn (Enter / Tab queue) **not verified yet** |
| Queue | block in `UserPromptSubmit`, replay with `Stop` → `decision: "block"` (the reason becomes a new prompt) | Documented, not verified |
| Interrupt | `PreToolUse` `continue:false` is not supported yet; only single tool calls can be denied | ⚠️ No clean hook path. A reliable stop likely needs the App Server `turn/interrupt` |
| Detect Esc | `Interrupt` hook | Documented, not verified |

Codex also asks you to trust each hook before it runs (`/hooks`).

## Plan

1. Probe mid-turn behaviour: Enter (native steer), Tab (native queue) and Esc.
2. If `UserPromptSubmit` fires mid-turn with the active `turn_id`, port [`../claude-code/scripts/jev_router.py`](../claude-code/scripts/jev_router.py) to `codex/`.
3. Ship it as a `hooks.json` snippet you can merge into `~/.codex/hooks.json`.

Results will be added to [`../docs/test-results.md`](../docs/test-results.md).
