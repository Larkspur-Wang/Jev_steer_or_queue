# Codex CLI · `jev-steer-or-queue`

[← Back to the project README](../README.md)

Codex hooks are scripts plus a `hooks.json`, not a plugin bundle, so this adapter is [`hooks.example.json`](hooks.example.json) plus the router in [`scripts/jev_router.py`](scripts/jev_router.py). Tested on Codex CLI 0.156.1.

## Install

1. Put the router somewhere permanent and point the hooks at it:

   ```bash
   mkdir -p ~/.jev-steer-or-queue
   cp scripts/jev_router.py ~/.jev-steer-or-queue/
   sed "s#/ABSOLUTE/PATH/TO/jev_router.py#$HOME/.jev-steer-or-queue/jev_router.py#" \
     hooks.example.json > ~/.codex/hooks.json
   ```

   Merging into an existing `~/.codex/hooks.json` also works: Codex loads user, project and plugin hooks together, and only one form per layer.

2. Write a config file, because Codex hook entries carry no plugin options:

   ```bash
   cat > ~/.jev-steer-or-queue/config.json <<'JSON'
   { "TYPESAFE_API_KEY": "sk-...", "MODE": "shadow" }
   JSON
   chmod 600 ~/.jev-steer-or-queue/config.json
   ```

   `MODE` is `shadow` (only logs) or `active`. Every option in the [Claude Code README](../claude-code/README.md#configuration) works here too, either in this file or as a `JEV_ROUTER_*` environment variable.

3. Trust the hooks: run `/hooks` in Codex, or start with `--dangerously-bypass-hook-trust` for a single run.

4. Log (Codex has no `${CLAUDE_PLUGIN_DATA}`): `~/.jev-steer-or-queue/log.jsonl`.

## How Codex differs from Claude Code

`UserPromptSubmit` fires for a message you type mid-turn, with `turn_id` set to the running turn — that part is like Claude Code. Two things are not:

**Blocking wedges the turn.** Returning `{"decision": "block"}` for a mid-turn prompt leaves the turn with no further model call and no `Stop` event, so the TUI sits there until you press Esc. The router therefore never blocks in Codex. Instead it adds a note as `additionalContext`:

- **queue** → *"[jev] The message above is a queued request … Do not act on it now. Finish every step you already planned, then handle it."*
- **interrupt** → *"[jev] The message above asks you to stop … Do not call any more tools"*, and the next `PreToolUse` returns `permissionDecision: "deny"`.

This is a nudge, not a guarantee: it depends on the model following the note. Verified working on GPT-6-Luna, but a weaker model may ignore it.

**Typing with Tab already queues.** Codex's native queue does exactly what this plugin would do for a "queue" message, and its native Enter steering matches "steer". `UserPromptSubmit` does **not** fire for a Tab-queued message; it arrives later as a fresh turn. So the router only ever sees steer-shaped input, and its real job in Codex is to recognise the cases where Enter was the wrong choice:

| You do | Codex native | With this adapter |
| :--- | :--- | :--- |
| Enter, “use the simpler approach” | steers | steers (Jev: allow) |
| Enter, “when you're done, update the README” | steers, mixing it into the current task | Jev adds a note to finish first, then handle it |
| Enter, “stop, don't continue” | steers; Codex keeps working | Jev adds a stop note and denies further tool calls |
| Tab, anything | queues until the turn ends | unchanged; hooks never see it |
| Esc | interrupts | unchanged; the `Interrupt` hook fires for logging only |

## What the hooks see

| Event | Fields | Notes |
| :--- | :--- | :--- |
| `SessionStart` | `source` | Fires per session, including Codex's own internal sessions |
| `UserPromptSubmit` | `prompt`, `turn_id`, `session_id` | Also fires for prompts Codex generates itself (see below) |
| `PreToolUse` / `PostToolUse` | `tool_name`, `tool_input`, `tool_use_id`, `turn_id` | `PreToolUse` can deny one call; `continue:false` is not supported yet |
| `Stop` | `turn_id` | Requires JSON on stdout on exit 0 |
| `Interrupt` | — | Fires when you press Esc; timeout is clamped to 3 s |

## Known limitations

- **Codex fires `UserPromptSubmit` for its own prompts** (memory consolidation, subagent sessions, auto-review). Those are filtered by a marker list in the router (`INTERNAL_MARKERS`), and an unclassified first prompt only becomes "the current task" if no turn is running. Extend the list if you see an internal prompt leak into the context.
- Steering is a plain text injection, so the model can ignore both the message and Jev's note.
- The `PreToolUse` deny can only reject one tool call at a time; there is no hook-level cancel. For a hard stop, use Codex's own Esc or the App Server's `turn/interrupt`.
- `Interrupt` hook timeouts are clamped to 3 seconds, so keep this router fast (it fails open).
