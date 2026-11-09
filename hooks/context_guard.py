"""UserPromptSubmit hook: session-length watchdog (model-picker plugin).

Every message resends the whole session history, so a long session gets pricier each step.
The script reads the context size of the last reply from the transcript and, if it exceeds the threshold:
- adds a reminder for Claude: a full mandatory instruction at each new level, a short one in between;
- shows the user one UI line at each level (threshold, +100k, +200k).
The threshold is set by the CONTEXT_GUARD_WARN env var (tokens, default 150000).
Never blocks work: any error is a silent exit with code 0.
"""
import json
import os
import sys

DEFAULT_WARN = 150_000
STEP = 100_000              # next levels for the user line: WARN + STEP, WARN + 2 * STEP
TAIL_BYTES = 4 * 1024 * 1024
KEEP_SESSIONS = 100


def warn_threshold():
    try:
        value = int(os.environ.get("CONTEXT_GUARD_WARN", DEFAULT_WARN))
    except ValueError:
        return DEFAULT_WARN
    return value if value > 0 else DEFAULT_WARN


def state_path():
    """State lives in the plugin data dir (survives updates); without a plugin, next to the script."""
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ".context_guard.json")


def last_context(path):
    """Input size of the last assistant reply: input + cache read + cache write."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        msg = d.get("message")
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            continue
        total = sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        if total:
            return total
    return 0


def new_level(session, ctx, levels):
    """Highest level in levels not yet announced in this session, else 0. Remembers the announced one."""
    path = state_path()
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    level = max((n for n in levels if ctx >= n), default=0)
    if level <= state.get(session, 0):
        return 0
    state.pop(session, None)                    # move the updated session to the end so pruning keeps it
    state[session] = level
    state = dict(list(state.items())[-KEEP_SESSIONS:])
    tmp = "{0}.{1}.tmp".format(path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)                   # atomic: parallel sessions cannot corrupt the file
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return level


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    path = data.get("transcript_path")
    if not path or not os.path.isfile(path):
        return
    warn = warn_threshold()
    ctx = last_context(path)
    if ctx < warn:
        return
    k = round(ctx / 1000)
    level = new_level(data.get("session_id") or "?", ctx, (warn, warn + STEP, warn + 2 * STEP))
    if level:
        # A new level was just reached: an unconditional instruction (a conditional "if it is a new task"
        # was ignored in practice, because every message in a long session looks like a continuation).
        note = (
            "Session watchdog, MANDATORY: context ~{0}k tokens (threshold {1}k); every step resends the whole history, "
            "and the user was just warned in the UI. Do NOT stay silent and do NOT wait for a new task: even if the "
            "user's message is a plain continuation, at the first natural stopping point of this turn (not mid-edit) "
            "tell the user in one line that the session is long and offer to continue in a new session with a short "
            "brief: what's done, what's next, which files, where the plan is. "
            "In the Claude app do it with start_session, not text: initiation \"own_initiative\", context \"fresh\", full "
            "brief (the card is the user's consent); if the user's last message names a separate task, use \"offer\" "
            "(only title, separate call at the start of the message); \"user_asked\" only if the user literally asked "
            "to start it now. Load the pick-model skill before start_session and Agent. If start_session is not loaded, "
            "first ToolSearch \"select:mcp__ccd_session__start_session\" in a separate message. Model and effort per "
            "pick-model; offer takes none and other launches are capped at the parent's values, so after launch check "
            "get_session and, if short, set the recommended via set_session_model and set_session_effort. "
            "In the terminal, suggest /clear or a new claude window and give the brief as one block. "
            "If the user declines, continue here and do not repeat until the next level."
        ).format(k, warn // 1000)
    else:
        note = (
            "Session watchdog: context ~{0}k tokens (threshold {1}k). If you have not yet offered a new session "
            "since the last warning, do it at the next natural stopping point (see pick-model skill); "
            "if the user already declined, say nothing."
        ).format(k, warn // 1000)
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": note}}
    if level:
        out["systemMessage"] = (
            "Сессия длинная: ~{0} тыс. токенов контекста, каждое сообщение отправляет всю историю заново. "
            "Следующую задачу дешевле начать в новой сессии.".format(k))
    sys.stdout.write(json.dumps(out, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:       # the hook must not break message submission
        pass
    sys.exit(0)
