"""Хук UserPromptSubmit: сторож длины сессии (плагин model-picker).

Каждое сообщение заново отправляет модели всю историю сессии, поэтому длинная сессия дорожает с каждым шагом.
Скрипт берёт размер контекста последнего ответа из транскрипта и, если он больше порога:
- добавляет Claude напоминание: новую задачу или следующий шаг — предложить в новой сессии;
- пользователю один раз на каждом пороге (порог, +100 тыс., +200 тыс.) показывает строку в интерфейсе.
Порог задаёт переменная окружения CONTEXT_GUARD_WARN (в токенах, по умолчанию 150000).
Никогда не мешает работе: любая ошибка — тихий выход с кодом 0.
"""
import json
import os
import sys

DEFAULT_WARN = 150_000
STEP = 100_000              # следующие пороги для строки пользователю: WARN + STEP, WARN + 2 * STEP
TAIL_BYTES = 4 * 1024 * 1024
KEEP_SESSIONS = 100


def warn_threshold():
    try:
        value = int(os.environ.get("CONTEXT_GUARD_WARN", DEFAULT_WARN))
    except ValueError:
        return DEFAULT_WARN
    return value if value > 0 else DEFAULT_WARN


def state_path():
    """Состояние — в папке данных плагина (переживает обновления), без плагина — рядом со скриптом."""
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ".context_guard.json")


def last_context(path):
    """Размер входа последнего ответа ассистента: input + чтение кэша + запись в кэш."""
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
    """Самый высокий порог из levels, который ещё не объявляли в этой сессии, иначе 0. Запоминает объявленный."""
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
    state.pop(session, None)                    # обновлённую сессию — в конец, чтобы чистка её не тронула
    state[session] = level
    state = dict(list(state.items())[-KEEP_SESSIONS:])
    tmp = "{0}.{1}.tmp".format(path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)                   # атомарно: параллельные сессии не испортят файл
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
    out = {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": (
            "Сторож сессии: контекст ~{0} тыс. токенов (порог {1} тыс.), каждый шаг заново отправляет всю историю. "
            "Если сообщение пользователя — новая задача, следующий шаг плана или работа, которой эта история не нужна, "
            "сначала предложи вынести её в новую сессию с коротким брифом: что сделано, что дальше, какие файлы, где план. "
            "В приложении Claude — всегда вызов start_session, не текст: задача из последнего сообщения пользователя — "
            "initiation \"offer\" (только title, отдельным вызовом в начале сообщения), следующий шаг, который заметил "
            "ты сам, — \"own_initiative\" с брифом; \"user_asked\" (старт без карточки) — только если пользователь "
            "в последнем сообщении дословно попросил запустить сессию сразу, иначе карточка обязательна всегда. "
            "Перед каждым start_session и Agent обязательно загрузи скилл pick-model. Если start_session не загружен, сначала ToolSearch "
            "\"select:mcp__ccd_session__start_session\" отдельным сообщением. Модель и effort — по скиллу pick-model; "
            "start_session ограничивает их значениями родителя, поэтому после запуска проверь get_session и при нехватке "
            "выставь рекомендованные через set_session_model и set_session_effort. "
            "В терминале — предложи /clear или новое окно claude и дай бриф одним блоком. "
            "Вопрос, мелкую правку или доделку текущей задачи делай здесь."
        ).format(k, warn // 1000),
    }}
    if new_level(data.get("session_id") or "?", ctx, (warn, warn + STEP, warn + 2 * STEP)):
        out["systemMessage"] = (
            "Сессия длинная: ~{0} тыс. токенов контекста, каждое сообщение отправляет всю историю заново. "
            "Следующую задачу дешевле начать в новой сессии.".format(k))
    sys.stdout.write(json.dumps(out, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:       # хук не должен ломать отправку сообщения
        pass
    sys.exit(0)
