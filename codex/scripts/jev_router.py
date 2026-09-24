#!/usr/bin/env python3
"""Jev steer / queue / interrupt router for coding-agent CLI hooks.

Usage: jev_router.py <claude|codex>

The client argument picks the session model; the Codex branch lives in a copy of this file.

  steer      allow; the client injects the message natively
  queue      hold it and replay it after the turn (Claude Code blocks and replays
             from the Stop hook; Codex, where blocking wedges the turn, annotates)
  interrupt  stop the turn (Claude Code: continue:false at the next tool hook;
             Codex: an annotation plus a denied tool call)

In shadow mode (the default) nothing is blocked or stopped; decisions are only
logged. Any error or timeout falls back to "allow", i.e. native behaviour.

Standard library only; Python 3.8+.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
MAX_MESSAGE_CHARS = 2000
# Codex fires UserPromptSubmit for prompts it generates itself. Those must never
# become the "current task" the router classifies the next message against.
INTERNAL_MARKERS = ("Memory Writing Agent", "rollout summaries", "## Memory")
MAX_TASK_CHARS = 500


def option(name: str, default: str = "") -> str:
    """JEV_ROUTER_<NAME> env overrides the plugin option CLAUDE_PLUGIN_OPTION_<NAME>."""
    for key in ("JEV_ROUTER_" + name, "CLAUDE_PLUGIN_OPTION_" + name):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    value = config().get(name)
    return str(value).strip() if value is not None else default


def config() -> Dict[str, Any]:
    """Optional JSON config for clients whose hooks cannot carry plugin options.

    ~/.jev-steer-or-queue/config.json: {"TYPESAFE_API_KEY": "...", "MODE": "active"}
    """
    path = os.path.join(os.path.expanduser("~/.jev-steer-or-queue"), "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}

def number(name: str, default: float) -> float:
    try:
        return float(option(name, str(default)))
    except ValueError:
        return default


def api_key() -> str:
    return option("TYPESAFE_API_KEY") or os.environ.get("TYPESAFE_API_KEY", "").strip()


def data_dir() -> str:
    path = os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("JEV_ROUTER_DATA") \
        or os.path.expanduser("~/.jev-steer-or-queue")
    os.makedirs(os.path.join(path, "sessions"), exist_ok=True)
    return path


# ---------------------------------------------------------------- session files


class Session:
    def __init__(self, root: str, session_id: str) -> None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id or "unknown")
        base = os.path.join(root, "sessions", safe)
        self.state_path = base + ".json"
        self.queue_path = base + ".queue.jsonl"
        self._lock = open(base + ".lock", "a")
        fcntl.flock(self._lock, fcntl.LOCK_EX)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def save(self, state: Dict[str, Any]) -> None:
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    def push(self, prompt: str) -> None:
        with open(self.queue_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"prompt": prompt, "ts": time.time()}, ensure_ascii=False) + "\n")

    def items(self) -> List[str]:
        try:
            with open(self.queue_path, encoding="utf-8") as fh:
                return [json.loads(line)["prompt"] for line in fh if line.strip()]
        except (OSError, ValueError, KeyError):
            return []

    def pop(self) -> Optional[str]:
        items = self.items()
        if not items:
            return None
        self._rewrite(items[1:])
        return items[0]

    def drain(self) -> List[str]:
        items = self.items()
        self._rewrite([])
        return items

    def _rewrite(self, items: List[str]) -> None:
        with open(self.queue_path, "w", encoding="utf-8") as fh:
            for prompt in items:
                fh.write(json.dumps({"prompt": prompt}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- Jev


def ask_jev(message: str, active_task: str) -> Dict[str, Any]:
    key = api_key()
    if not key:
        return {"error": "missing_api_key"}
    body = {
        "model": option("JEV_MODEL", "jev-latest"),
        "state": {
            "new_message": message[:MAX_MESSAGE_CHARS],
            "active_task": active_task[:MAX_TASK_CHARS],
        },
        "questions": {
            "timing": {
                "type": "choice",
                "instructions": (
                    "`new_message` 是用户在编码助手执行 `active_task` 期间发来的新消息。"
                    "这条消息与当前正在执行的任务是什么时间关系？"
                ),
                "criteria": {
                    "steer": "现在就改变正在执行的任务的要求、范围或做法，任务继续",
                    "queue": "与当前任务无关或明确要求当前任务完成后再处理的新请求",
                    "interrupt": "明确要求立刻停止或放弃当前正在执行的任务",
                    "unclear": "无法判断与当前任务的关系，或同时包含多种意图",
                },
            },
            "explicit_stop": {
                "type": "noul",
                "instructions": "`new_message` 是否明确要求立刻停止当前正在执行的任务？",
                "criteria": {
                    "true": "明确的立即停止、取消或不要继续当前任务",
                    "false": "没有明确要求停止，包括普通纠正、补充要求或后续任务",
                },
            },
        },
    }
    req = urllib.request.Request(
        option("TYPESAFE_API_URL", DEFAULT_URL),
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=number("TIMEOUT_S", 2.0)) as resp:
            answers = json.loads(resp.read().decode("utf-8")).get("answers") or {}
    except urllib.error.HTTPError as exc:
        return {"error": "http_{0}".format(exc.code), "ms": elapsed_ms(started)}
    except Exception as exc:  # timeout, DNS, bad JSON: fail open
        return {"error": type(exc).__name__, "ms": elapsed_ms(started)}
    timing = answers.get("timing") or {}
    return {
        "choice": timing.get("choice"),
        "probabilities": timing.get("probabilities") or {},
        "explicit_stop": float((answers.get("explicit_stop") or {}).get("noul") or 0.0),
        "ms": elapsed_ms(started),
    }


def elapsed_ms(started: float) -> int:
    return int((time.time() - started) * 1000)


def decide(jev: Dict[str, Any]) -> str:
    """Only confident queue / interrupt change behaviour; everything else stays native."""
    probs = jev.get("probabilities") or {}
    stop = jev.get("explicit_stop", 0.0)
    if probs.get("interrupt", 0.0) >= number("INTERRUPT_THRESHOLD", 0.9) and stop >= number("INTERRUPT_THRESHOLD", 0.9):
        return "interrupt"
    if probs.get("queue", 0.0) >= number("QUEUE_THRESHOLD", 0.9) and stop < 0.5:
        return "queue"
    return "steer"


# ---------------------------------------------------------------- hook handlers


def on_prompt(client: str, payload: Dict[str, Any], session: Session, state: Dict[str, Any], record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    prompt = str(payload.get("prompt") or "")
    if client == "codex" and any(marker in prompt for marker in INTERNAL_MARKERS):
        record["internal"] = True
        return None
    if client == "codex":
        return codex_prompt(payload, session, state, record, prompt)
    prompt_id = payload.get("prompt_id")
    # A mid-turn message carries the running turn's prompt_id; a new turn gets a
    # fresh one. This stays correct after Esc, which fires no hook at all.
    if prompt_id:
        mid_turn = prompt_id == state.get("prompt_id") and state.get("active", False)
    else:
        mid_turn = bool(state.get("active"))
    record["mid_turn"] = mid_turn

    if not mid_turn:
        leftover = session.drain()
        state.clear()
        state.update({"active": True, "prompt_id": prompt_id, "task": prompt[:MAX_TASK_CHARS], "stop": False})
        if leftover:
            record["dropped"] = len(leftover)
            return {"systemMessage": "上一轮没有正常结束，{0} 条排队消息未发送（已丢弃，需要请重发）：\n{1}".format(
                len(leftover), "\n".join("- " + p[:200] for p in leftover))}
        return None

    jev = ask_jev(prompt, state.get("task", ""))
    action = decide(jev) if "error" not in jev else "steer"
    record.update({"jev": jev, "action": action})
    if option("MODE", "shadow") != "active" or action == "steer":
        return None

    label = "{0} {1:.2f}".format(action, (jev.get("probabilities") or {}).get(action, 0.0))
    if action == "queue":
        session.push(prompt)
        return {"decision": "block", "reason": "已排队（Jev {0}），本轮结束后发送：{1}".format(label, prompt[:120])}
    state["stop"] = True
    return {"decision": "block", "reason": "将停止当前任务（Jev {0}），在下一个工具边界生效。".format(label)}


def codex_prompt(payload: Dict[str, Any], session: Session, state: Dict[str, Any],
                 record: Dict[str, Any], prompt: str) -> Optional[Dict[str, Any]]:
    """Codex: turn_id tells us whether a prompt is mid-turn; blocking wedges the turn."""
    turn_id = payload.get("turn_id")
    mid_turn = bool(state.get("active")) and turn_id == state.get("turn")
    record["mid_turn"] = mid_turn
    if not mid_turn:
        if not state.get("active"):
            state.update({"active": True, "turn": turn_id, "task": prompt[:MAX_TASK_CHARS], "stop": False})
        return None
    jev = ask_jev(prompt, state.get("task", ""))
    action = decide(jev) if "error" not in jev else "steer"
    record.update({"jev": jev, "action": action})
    if option("MODE", "shadow") != "active" or action == "steer":
        return None
    label = "{0} {1:.2f}".format(action, (jev.get("probabilities") or {}).get(action, 0.0))
    if action == "queue":
        text = ("[jev] The message above is a queued request (Jev {0}): it is unrelated to the current task. "
                "Do not act on it now. Finish every step you already planned, then handle it.".format(label))
    else:
        state["stop"] = True
        text = ("[jev] The message above asks you to stop (Jev {0}): stop the current task now. "
                "Do not call any more tools; say in one line what is finished and what is not, then end the turn.".format(label))
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def codex_tool(event: str, state: Dict[str, Any], record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not state.get("stop"):
        return None
    if event == "PreToolUse":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "The user asked to stop this task; do not call more tools."}}
    state.update({"active": False, "stop": False})
    record["action"] = "stop_after_tool"
    return None


def on_tool(state: Dict[str, Any], session: Session, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not state.get("stop"):
        return None
    state.update({"active": False, "stop": False})
    record["action"] = "hard_stop"
    reason = "Jev：已按你的要求停止当前任务。"
    dropped = session.drain()
    if dropped:
        reason += " 另有 {0} 条排队消息未执行：{1}".format(len(dropped), "；".join(p[:120] for p in dropped))
    return {"continue": False, "stopReason": reason}


def on_stop(state: Dict[str, Any], session: Session, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    queued = session.pop() if option("MODE", "shadow") == "active" else None
    if not queued:
        state.update({"active": False, "stop": False})
        return None
    record["action"] = "dequeue"
    state.update({"task": queued[:MAX_TASK_CHARS], "stop": False})
    return {"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": "用户在上一段任务执行期间发来一条排队消息，现在请处理它：\n" + queued,
    }}


def main() -> int:
    client = sys.argv[1] if len(sys.argv) > 1 else "codex"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    event = payload.get("hook_event_name", "")
    root = data_dir()
    session = Session(root, str(payload.get("session_id") or ""))
    state = session.load()
    record: Dict[str, Any] = {"ts": round(time.time(), 3), "event": event,
                              "session": payload.get("session_id"), "mode": option("MODE", "shadow")}

    out: Optional[Dict[str, Any]] = None
    if event == "UserPromptSubmit":
        out = on_prompt(client, payload, session, state, record)
        if option("LOG_PROMPTS", "true").lower() != "false":
            record["prompt"] = str(payload.get("prompt") or "")[:300]
    elif event in ("PreToolUse", "PostToolUse"):
        out = codex_tool(event, state, record) if client == "codex" else on_tool(state, session, record)
    elif event == "Stop":
        out = on_stop(state, session, record)
    elif event in ("StopFailure", "Interrupt"):
        state.update({"active": False, "stop": False})
    session.save(state)

    if event == "UserPromptSubmit" or "action" in record:
        if out is not None:
            record["output"] = out
        with open(os.path.join(root, "log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    if out is not None:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never break the host session
        sys.exit(0)
