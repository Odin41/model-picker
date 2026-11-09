---
name: pick-model
description: "Pick model and effort by task difficulty, and the one-task-one-session rule. MANDATORY: load BEFORE every start_session and every subagent (Agent) launch; do not start sessions or subagents without this skill. Also load when a task is done and the next one should be offered, when the watchdog reports a long context, and when the user asks which model or effort to use."
---

# Model and effort by task

**Never start sessions without this skill.** Load it before every `start_session` and every `Agent`.

Goal: the cheapest model that does the task right the first time. Redoing costs more than going one step up, so when unsure go one step higher, not straight to the top.

## Ladder

| Step | Task | Model | Effort |
|---|---|---|---|
| 1 | Question, search and reading code, rename, edit a document, report from ready data | `claude-haiku-5-5` | `low` |
| 2 | Work from a pattern: content, templates, small bug with a clear cause, tests for existing code | `claude-sonnet-5-5` | `medium` |
| 3 | Ordinary multi-file feature, bug with unclear cause, porting logic from a ready source | `claude-sonnet-5-5` | `high` |
| 4 | Architecture, complex mechanics and algorithms, money and user (player) data, security, reviewing others' work when errors are costly | `claude-opus-5-5` | `high` |

`claude-fable-5-1` (stronger and pricier than Opus) and effort `xhigh` / `max` only if the user asks.

Price/strength order: Haiku < Sonnet < Opus < Fable. Expensive models also burn the subscription limit faster. If newer models exist, use the current IDs of the same line.

## Picking the step

Answer three questions, take the highest step:

1. **Is it clear what and where to change?** Yes: 1–2. No, needs investigation first: 3+.
2. **How much is touched?** One or two files by pattern: 2. Several related files: 3. System design changes: 4.
3. **Cost of error?** Easy to spot and roll back: lower. Money, data, security, irreversible actions: 4.

## Where to apply

- **New session in the Claude app (`start_session`).** Never "offer a new session" in text only — always call `start_session`:
  - a task the user named in their last message: `initiation: "offer"`, only `title`, as a separate call at the start of the message. Before the call: a title line and one sentence with the chosen model and effort; the brief goes in a second call with `proposal_id` once the user picks "New session";
  - an independent next task you noticed yourself (not a continuation of the current one): `initiation: "own_initiative"` with a full brief, `model` (full ID from the table) and `effort`;
  - `initiation: "user_asked"` (starts at once, no card) only if the user's last message literally asked to start the session right now ("start it now"). In all other cases, including "move it to a separate session" and "do the task", only a card (`offer` / `own_initiative`).
  Asking the user (the card) is always mandatory. Saying "Starting a session" without a card is forbidden.
  If `start_session` is not loaded (deferred tool), first load it via `ToolSearch` with query `select:mcp__ccd_session__start_session`, in a separate message.
  **Parameters.** `offer` takes no model/effort (first call: only `title`; second: only `proposal_id`, `prompt`, `background`) — the session starts with what the card selects, usually the parent's settings. `own_initiative` and `user_asked` cap model and effort at the parent's: requested `high` under a `medium` parent becomes `medium`, though the card shows the requested value. So for any `initiation`:
  1. Before launch, compare the ladder's model/effort with yours. If the ladder needs more, say so in one line and launch anyway.
  2. After launch, when `start_session` returns the session id, check the real values via `mcp__ccd_session_mgmt__get_session`. If model or effort is below the recommended, set them via `mcp__ccd_session_mgmt__set_session_model` and `mcp__ccd_session_mgmt__set_session_effort` (the app asks the user per change). Report the outcome in one line with the real values.
- **Subagent (`Agent`).** `model` takes aliases `haiku` / `sonnet` / `opus`, `effort` per the table. Finding a line / reading: `haiku` + `low`; if the subagent must understand how unfamiliar code works rather than locate something: `sonnet` + `medium`. `subagent_type: "fork"` takes no model: a fork always uses the session's model.
- **Terminal (Claude Code CLI).** No `start_session`: suggest starting the next task after `/clear` or in a new `claude` window, and give the brief as one paste-ready block. The user changes model with `/model`.
- **Current session.** A session cannot change its own model. If much work ahead is clearly below or above the current model's level, suggest in one line that the user switch models.

State the choice in one line in the launch message, e.g. "Sonnet 5.5 / high — three-file feature, cause is clear".

## If the model falls short

Two failed attempts at one step: say so plainly and go up one step (1 → 2 → 3 → 4); don't try a third time. For a running app session you can suggest `set_session_model` — the app asks the user. At step 4: go to the user — split the task or use Fable.

## One task, one session

Every message resends the whole history, so a long session gets pricier each step.

- Task done (and committed) and an **independent** next task remains: offer it via an `own_initiative` card with a short brief: what's done, what's next, which files, where the plan is. Model and effort per the ladder. If there's no such task, offer nothing and invent nothing.
- Direct continuation of what was just done (next iteration, "go ahead" after analysis, fixes from results), questions and small edits stay in this session: the context is already here, a new session would have to rebuild it. Only work that doesn't need this session's history goes to a new session.
- **Watchdog.** This plugin's hook injects `Session watchdog` into the context when it passes the threshold (default 150k tokens). It is an instruction, not background noise: never ignore it. At each new level (150k, 250k, 350k) the message is marked MANDATORY: at the first natural stopping point of that turn, tell the user in one line the session is long and offer to continue in a new session with a brief (`own_initiative` card in the app). This applies even to a plain continuation: the rule above \"continuation stays here\" is overridden once the watchdog fires. If the user declines, continue here and do not repeat until the next level. Short watchdog reminders between levels: offer only if you have not offered since the last level.
