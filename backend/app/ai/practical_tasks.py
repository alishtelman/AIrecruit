"""
Practical task bank and plan generator for voice-first interview mode.

Architecture:
  - TASK_BANK: full task records including hidden fields (expected_solution,
    evaluation_rubric). These NEVER leave the backend.
  - get_task_for_frontend(): strips hidden fields before API serialization.
  - get_practical_plan(): returns an ordered list of task_ids for an interview,
    based on role + seniority. Stored in interview_state["practical_task_plan"].
  - should_trigger_next_practical_task(): checks whether the next task in the
    plan should fire now (replaces the old single-trigger logic).

Hidden fields (backend-only, never in API response):
  - expected_solution: reference answer used only by the evaluator
  - evaluation_rubric: detailed scoring criteria used by the evaluator

Public fields (safe to send to frontend):
  - task_id, task_type, title, instruction, language, starter_code,
    examples, evaluation_criteria (labels only), time_limit_minutes,
    voice_intro, task_index, task_total
"""
import random
import uuid
from typing import Literal

# ---------------------------------------------------------------------------
# Trigger policy constants
# ---------------------------------------------------------------------------

MIN_ANSWERS_BEFORE_PRACTICAL = 3   # need at least 3 voice answers before first task
MAX_ANSWERS_BEFORE_PRACTICAL = 7   # don't trigger after 7 (too close to end)
BETWEEN_TASKS_MIN_ANSWERS = 2      # answers needed between two practical tasks

# Tasks per seniority level
TASKS_BY_LEVEL: dict[str, int] = {
    "junior": 2,
    "middle": 3,
    "senior": 4,
    None: 2,   # type: ignore[index]  # fallback when seniority unknown
}

# Stage keys where practical tasks are appropriate
PRACTICAL_TASK_ALLOWED_STAGES = {
    "",                  # no stage set (simple interview)
    "technical",
    "technical_case",
    "technical_validation",
    "practical_case",
    "resume_followup",
    "resume_deep_dive",
}

# Roles that receive practical tasks
PRACTICAL_TASK_ROLES = {
    "backend_engineer",
    "frontend_engineer",
    "qa_engineer",
    "devops_engineer",
    "data_scientist",
    "product_manager",
    "mobile_engineer",
}

# ---------------------------------------------------------------------------
# Full task bank (including hidden backend-only fields)
# ---------------------------------------------------------------------------

TASK_BANK: dict[str, list[dict]] = {

    # ── Backend Engineer ─────────────────────────────────────────────────────
    "backend_engineer": [
        {
            "id": "be_validate_registration",
            "difficulty": "junior",
            "task_type": "coding_task",
            "title_ru": "Валидация входящих данных",
            "title_en": "Request payload validation",
            "instruction_ru": (
                "Напишите функцию `validate_registration(data: dict) -> dict`, "
                "которая проверяет данные регистрации пользователя.\n\n"
                "Поля: `email` (строка, обязательное), `password` (строка, минимум 8 символов), "
                "`age` (целое, от 18 до 120).\n\n"
                "Верните `{\"valid\": true}` или `{\"valid\": false, \"errors\": [...]}`."
            ),
            "instruction_en": (
                "Write `validate_registration(data: dict) -> dict` "
                "that validates user registration payload.\n\n"
                "Fields: `email` (string, required), `password` (string, min 8 chars), "
                "`age` (integer, 18–120).\n\n"
                "Return `{\"valid\": True}` or `{\"valid\": False, \"errors\": [...]}`."
            ),
            "voice_intro_ru": "Открою практическое задание — валидация входящих данных.",
            "voice_intro_en": "I'll open a coding task — request payload validation.",
            "language": "python",
            "starter_code": (
                "def validate_registration(data: dict) -> dict:\n"
                "    \"\"\"\n"
                "    Validates user registration data.\n"
                "    Returns {\"valid\": True} or {\"valid\": False, \"errors\": [...]}\n"
                "    \"\"\"\n"
                "    # implement here\n"
                "    pass\n"
            ),
            # BACKEND ONLY — never sent to frontend
            "expected_solution": (
                "def validate_registration(data: dict) -> dict:\n"
                "    errors = []\n"
                "    if not str(data.get('email', '')).strip():\n"
                "        errors.append('email required')\n"
                "    if len(str(data.get('password', ''))) < 8:\n"
                "        errors.append('password too short')\n"
                "    age = data.get('age')\n"
                "    if not isinstance(age, int) or not (18 <= age <= 120):\n"
                "        errors.append('age must be 18–120')\n"
                "    return {'valid': not errors, 'errors': errors}\n"
            ),
            "evaluation_rubric": (
                "Award points: email check (2), password length (2), "
                "age range check (2), returns dict with valid+errors (2), "
                "handles missing keys without exception (2). Max 10."
            ),
            "examples": [
                {"input": '{"email": "a@b.com", "password": "secret123", "age": 25}', "output": '{"valid": true}'},
                {"input": '{"email": "", "password": "x", "age": 15}', "output": '{"valid": false, "errors": [...]}'},
            ],
            "evaluation_criteria": ["Корректность", "Граничные значения", "Обработка ошибок"],
            "time_limit_minutes": 10,
        },
        {
            "id": "be_paginate_bug",
            "difficulty": "junior",
            "task_type": "debugging_task",
            "title_ru": "Найди баг в пагинации",
            "title_en": "Debug the pagination function",
            "instruction_ru": (
                "В функции ниже есть баг. Найдите и исправьте его.\n\n"
                "Функция должна возвращать срез `items` для страницы `page` (нумерация с 1)."
            ),
            "instruction_en": (
                "The function below has a bug. Find and fix it.\n\n"
                "It should return a slice of `items` for page `page` (1-indexed)."
            ),
            "voice_intro_ru": "Открою задание на отладку — нужно найти и исправить баг в коде.",
            "voice_intro_en": "I'll open a debugging task — find and fix the bug in the code.",
            "language": "python",
            "starter_code": (
                "def paginate(items: list, page: int, page_size: int) -> list:\n"
                "    \"\"\"\n"
                "    Returns items for a given page (1-indexed).\n"
                "    Bug is on the line below — find and fix it.\n"
                "    \"\"\"\n"
                "    start = page * page_size          # <-- bug here\n"
                "    end = start + page_size\n"
                "    return items[start:end]\n\n"
                "# Expected:\n"
                "# paginate([1,2,3,4,5], page=1, page_size=2) → [1, 2]\n"
                "# paginate([1,2,3,4,5], page=2, page_size=2) → [3, 4]\n"
            ),
            "expected_solution": (
                "def paginate(items, page, page_size):\n"
                "    start = (page - 1) * page_size\n"
                "    return items[start:start + page_size]\n"
            ),
            "evaluation_rubric": (
                "Identified the off-by-one (3), corrected to (page-1)*page_size (4), "
                "explained why the original was wrong (3). Max 10."
            ),
            "examples": [
                {"input": "page=1, page_size=2", "output": "[1, 2]"},
                {"input": "page=2, page_size=2", "output": "[3, 4]"},
            ],
            "evaluation_criteria": ["Нашёл баг", "Объяснение причины", "Правильное исправление"],
            "time_limit_minutes": 8,
        },
        {
            "id": "be_sql_join",
            "difficulty": "middle",
            "task_type": "sql_task",
            "title_ru": "SQL: пользователи без заказов за 30 дней",
            "title_en": "SQL: users with no orders in last 30 days",
            "instruction_ru": (
                "Таблицы: `users(id, email, created_at)`, `orders(id, user_id, created_at)`.\n\n"
                "Напишите запрос, который возвращает `id` и `email` всех пользователей, "
                "у которых нет заказов за последние 30 дней. "
                "Учесть пользователей, у которых вообще нет заказов."
            ),
            "instruction_en": (
                "Tables: `users(id, email, created_at)`, `orders(id, user_id, created_at)`.\n\n"
                "Write a query returning `id` and `email` of users who have NO orders "
                "in the last 30 days. Include users who have never ordered."
            ),
            "voice_intro_ru": "Открою SQL задание — запрос на пользователей без заказов.",
            "voice_intro_en": "I'll open a SQL task — users with no orders in 30 days.",
            "language": "sql",
            "starter_code": (
                "-- users(id INT, email TEXT, created_at TIMESTAMP)\n"
                "-- orders(id INT, user_id INT, created_at TIMESTAMP)\n\n"
                "SELECT u.id, u.email\n"
                "FROM users u\n"
                "-- write your JOIN / subquery here\n"
            ),
            "expected_solution": (
                "SELECT u.id, u.email\n"
                "FROM users u\n"
                "LEFT JOIN orders o\n"
                "  ON o.user_id = u.id\n"
                "  AND o.created_at >= NOW() - INTERVAL '30 days'\n"
                "WHERE o.id IS NULL;\n"
            ),
            "evaluation_rubric": (
                "LEFT JOIN with date filter in ON clause (4), WHERE o.id IS NULL (3), "
                "selects correct columns (2), no cartesian product risk (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Правильный JOIN", "Фильтрация дат", "Покрытие NULL-пользователей"],
            "time_limit_minutes": 10,
        },
        {
            "id": "be_rate_limit_design",
            "difficulty": "senior",
            "task_type": "system_design_task",
            "title_ru": "Дизайн rate limiter",
            "title_en": "Rate limiter design",
            "instruction_ru": (
                "Опишите дизайн простого rate limiter для REST API.\n\n"
                "Требования:\n"
                "- лимит: 100 запросов в минуту на пользователя\n"
                "- хранилище: Redis\n"
                "- точность: eventual (не строгая)\n\n"
                "Ответьте: какой алгоритм выберете (token bucket / sliding window / fixed window), "
                "как структурировать Redis-ключ, какой TTL выставить, "
                "и как обрабатывать превышение лимита."
            ),
            "instruction_en": (
                "Design a simple rate limiter for a REST API.\n\n"
                "Requirements:\n"
                "- Limit: 100 requests/minute per user\n"
                "- Storage: Redis\n"
                "- Accuracy: eventual (not strict)\n\n"
                "Describe: which algorithm (token bucket / sliding window / fixed window), "
                "Redis key structure, TTL, and how to handle limit exceeded."
            ),
            "voice_intro_ru": "Открою задание на проектирование — rate limiter на Redis.",
            "voice_intro_en": "I'll open a system design task — rate limiter with Redis.",
            "language": "text",
            "starter_code": (
                "Алгоритм: [token bucket / sliding window / fixed window]\n\n"
                "Redis ключ: ...\n\n"
                "TTL: ...\n\n"
                "При превышении: ...\n\n"
                "Псевдокод / команды Redis:\n"
            ),
            "expected_solution": (
                "Fixed window: key = 'rl:user:{uid}:minute:{unix_minute}', INCR + EXPIRE 60. "
                "Sliding window: sorted set with timestamps, ZADD + ZREMRANGEBYSCORE + ZCARD. "
                "Return 429 with Retry-After header on exceed."
            ),
            "evaluation_rubric": (
                "Algorithm choice with rationale (3), correct Redis commands (3), "
                "TTL strategy (2), 429 + Retry-After (2). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Выбор алгоритма", "Redis структура", "Обработка превышения"],
            "time_limit_minutes": 12,
        },
    ],

    # ── Frontend Engineer ────────────────────────────────────────────────────
    "frontend_engineer": [
        {
            "id": "fe_debounce",
            "difficulty": "junior",
            "task_type": "coding_task",
            "title_ru": "Функция debounce",
            "title_en": "Debounce function",
            "instruction_ru": (
                "Реализуйте функцию `debounce(fn, delay)`.\n\n"
                "Она должна возвращать обёртку, которая вызывает `fn` только спустя "
                "`delay` мс после последнего вызова. "
                "Каждый новый вызов до истечения задержки сбрасывает таймер."
            ),
            "instruction_en": (
                "Implement `debounce(fn, delay)`.\n\n"
                "It should return a wrapper that only calls `fn` after `delay` ms "
                "have elapsed since the last call. "
                "Each new call before the delay expires resets the timer."
            ),
            "voice_intro_ru": "Открою задание — реализуйте функцию debounce на JavaScript.",
            "voice_intro_en": "I'll open a coding task — implement debounce in JavaScript.",
            "language": "javascript",
            "starter_code": (
                "/**\n"
                " * @param {Function} fn\n"
                " * @param {number} delay - milliseconds\n"
                " * @returns {Function}\n"
                " */\n"
                "function debounce(fn, delay) {\n"
                "  // implement here\n"
                "}\n"
            ),
            "expected_solution": (
                "function debounce(fn, delay) {\n"
                "  let timer;\n"
                "  return function(...args) {\n"
                "    clearTimeout(timer);\n"
                "    timer = setTimeout(() => fn.apply(this, args), delay);\n"
                "  };\n"
                "}\n"
            ),
            "evaluation_rubric": (
                "Uses setTimeout (2), clears previous timer on each call (3), "
                "preserves `this` and args (2), returns a function (2), clean code (1). Max 10."
            ),
            "examples": [
                {"description": "3 rapid calls → only 1 real call after 300ms"},
            ],
            "evaluation_criteria": ["Сброс таймера", "Сохранение контекста", "Чистый код"],
            "time_limit_minutes": 8,
        },
        {
            "id": "fe_promise_chain",
            "difficulty": "junior",
            "task_type": "coding_task",
            "title_ru": "Обработка ошибок async/await",
            "title_en": "async/await error handling",
            "instruction_ru": (
                "Напишите функцию `fetchUserData(userId)`.\n\n"
                "Она делает fetch к `/api/users/{userId}`, "
                "при успехе возвращает `{id, name, email}`, "
                "при ошибке (HTTP 4xx/5xx или network error) возвращает `{error: string}`.\n\n"
                "Не должна бросать исключений наружу."
            ),
            "instruction_en": (
                "Write `fetchUserData(userId)`.\n\n"
                "It fetches `/api/users/{userId}`, "
                "on success returns `{id, name, email}`, "
                "on error (HTTP 4xx/5xx or network) returns `{error: string}`.\n\n"
                "Must not throw exceptions to the caller."
            ),
            "voice_intro_ru": "Открою задание — обработка ошибок в async/await.",
            "voice_intro_en": "I'll open a coding task — async/await error handling.",
            "language": "javascript",
            "starter_code": (
                "async function fetchUserData(userId) {\n"
                "  // implement here\n"
                "  // must not throw — return {error: '...'} on failure\n"
                "}\n"
            ),
            "expected_solution": (
                "async function fetchUserData(userId) {\n"
                "  try {\n"
                "    const res = await fetch(`/api/users/${userId}`);\n"
                "    if (!res.ok) return { error: `HTTP ${res.status}` };\n"
                "    return await res.json();\n"
                "  } catch (err) {\n"
                "    return { error: err.message };\n"
                "  }\n"
                "}\n"
            ),
            "evaluation_rubric": (
                "try/catch wrapping (2), checks res.ok (3), returns error object not throw (3), "
                "correct JSON parse (2). Max 10."
            ),
            "examples": [
                {"input": "userId=1, API returns 200", "output": "{id:1, name:'...', email:'...'}"},
                {"input": "userId=999, API returns 404", "output": "{error: 'HTTP 404'}"},
            ],
            "evaluation_criteria": ["try/catch", "HTTP статус", "Нет throws наружу"],
            "time_limit_minutes": 8,
        },
        {
            "id": "fe_react_counter",
            "difficulty": "middle",
            "task_type": "coding_task",
            "title_ru": "React компонент — счётчик с историей",
            "title_en": "React counter with undo",
            "instruction_ru": (
                "Напишите React-компонент `Counter`.\n\n"
                "Функционал:\n"
                "- кнопки +1, -1, Reset\n"
                "- кнопка Undo — отменяет последнее действие\n"
                "- счётчик не может уйти в минус (минимум 0)\n"
                "- показывает текущее значение\n\n"
                "Используйте только хуки. Не нужен Redux."
            ),
            "instruction_en": (
                "Write a React component `Counter`.\n\n"
                "Features:\n"
                "- +1, -1, Reset buttons\n"
                "- Undo button — reverts last action\n"
                "- Counter cannot go below 0\n"
                "- Shows current value\n\n"
                "Use hooks only. No Redux needed."
            ),
            "voice_intro_ru": "Открою задание — React компонент с историей действий.",
            "voice_intro_en": "I'll open a React coding task — counter with undo.",
            "language": "javascript",
            "starter_code": (
                "// React is available as a global (React.useState, etc.)\n"
                "// or use: import { useState } from 'react';\n\n"
                "function Counter() {\n"
                "  // implement here\n"
                "  return <div>Counter: 0</div>;\n"
                "}\n"
            ),
            "expected_solution": (
                "function Counter() {\n"
                "  const [count, setCount] = useState(0);\n"
                "  const [history, setHistory] = useState([]);\n"
                "  const push = (next) => { setHistory(h => [...h, count]); setCount(next); };\n"
                "  return (\n"
                "    <div>\n"
                "      <p>Count: {count}</p>\n"
                "      <button onClick={() => push(count + 1)}>+1</button>\n"
                "      <button onClick={() => push(Math.max(0, count - 1))}>-1</button>\n"
                "      <button onClick={() => push(0)}>Reset</button>\n"
                "      <button onClick={() => history.length && (setCount(history[history.length-1]), setHistory(h=>h.slice(0,-1)))}>Undo</button>\n"
                "    </div>\n"
                "  );\n"
                "}\n"
            ),
            "evaluation_rubric": (
                "useState for count and history (2), +/-/reset work (2), "
                "Undo pops history (3), floor at 0 (2), renders value (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["useState", "Undo с историей", "Ограничение min=0"],
            "time_limit_minutes": 12,
        },
        {
            "id": "fe_event_delegation",
            "difficulty": "junior",
            "task_type": "coding_task",
            "title_ru": "Event delegation — список с кнопками",
            "title_en": "Event delegation — list with delete buttons",
            "instruction_ru": (
                "Есть `<ul id=\"list\">` с элементами `<li data-id=\"N\"><button>Удалить</button> Item N</li>`.\n\n"
                "Напишите JavaScript, который удаляет элемент из DOM при клике на кнопку "
                "с помощью event delegation (один обработчик на `<ul>`, не на каждую кнопку)."
            ),
            "instruction_en": (
                "Given `<ul id=\"list\">` with items `<li data-id=\"N\"><button>Delete</button> Item N</li>`.\n\n"
                "Write JavaScript that removes an item from the DOM on button click "
                "using event delegation (one handler on `<ul>`, not on each button)."
            ),
            "voice_intro_ru": "Открою задание — event delegation, удаление элементов из списка.",
            "voice_intro_en": "I'll open a coding task — event delegation to delete list items.",
            "language": "javascript",
            "starter_code": (
                "// HTML:\n"
                "// <ul id=\"list\">\n"
                "//   <li data-id=\"1\"><button>Delete</button> Item 1</li>\n"
                "//   <li data-id=\"2\"><button>Delete</button> Item 2</li>\n"
                "// </ul>\n\n"
                "const list = document.getElementById('list');\n"
                "// add single event listener here using delegation\n"
            ),
            "expected_solution": (
                "list.addEventListener('click', (e) => {\n"
                "  if (e.target.tagName === 'BUTTON') {\n"
                "    e.target.closest('li').remove();\n"
                "  }\n"
                "});\n"
            ),
            "evaluation_rubric": (
                "Single listener on ul (3), checks target is button (3), "
                "removes correct li (3), uses closest or parentElement (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Delegation (не на кнопках)", "Правильное удаление", "Чистый код"],
            "time_limit_minutes": 8,
        },
        {
            "id": "fe_memo_optimization",
            "difficulty": "senior",
            "task_type": "coding_task",
            "title_ru": "Оптимизация React компонента",
            "title_en": "React component performance optimization",
            "instruction_ru": (
                "Компонент ниже перерендеривается слишком часто.\n\n"
                "Задача:\n"
                "1. Объясните причину лишних рендеров.\n"
                "2. Используйте `React.memo`, `useMemo` или `useCallback` для оптимизации.\n"
                "3. Ответьте: когда memo не поможет?"
            ),
            "instruction_en": (
                "The component below re-renders too often.\n\n"
                "Task:\n"
                "1. Explain the cause of excessive re-renders.\n"
                "2. Use `React.memo`, `useMemo`, or `useCallback` to optimize.\n"
                "3. Answer: when does memo NOT help?"
            ),
            "voice_intro_ru": "Открою задание — оптимизация React компонента.",
            "voice_intro_en": "I'll open a task — React performance optimization.",
            "language": "javascript",
            "starter_code": (
                "// Problem: ExpensiveList re-renders on every parent render\n"
                "// even when 'items' hasn't changed\n\n"
                "function Parent() {\n"
                "  const [count, setCount] = useState(0);\n"
                "  const items = ['a', 'b', 'c']; // <-- problem?\n"
                "  const handleClick = () => console.log('click'); // <-- problem?\n\n"
                "  return (\n"
                "    <div>\n"
                "      <button onClick={() => setCount(c => c + 1)}>Increment {count}</button>\n"
                "      <ExpensiveList items={items} onClick={handleClick} />\n"
                "    </div>\n"
                "  );\n"
                "}\n\n"
                "// Assume ExpensiveList is wrapped in React.memo.\n"
                "// Optimize Parent so ExpensiveList doesn't re-render unnecessarily.\n"
            ),
            "expected_solution": (
                "const items = useMemo(() => ['a','b','c'], []);\n"
                "const handleClick = useCallback(() => console.log('click'), []);\n"
                "// Memo doesn't help when props change by reference every render.\n"
            ),
            "evaluation_rubric": (
                "Identified referential equality issue (3), applied useMemo for array (2), "
                "applied useCallback for function (2), explained memo limits (3). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["useMemo/useCallback", "Причина ре-рендеров", "Ограничения memo"],
            "time_limit_minutes": 12,
        },
        {
            "id": "fe_throttle",
            "difficulty": "middle",
            "task_type": "coding_task",
            "title_ru": "Функция throttle",
            "title_en": "Throttle function",
            "instruction_ru": (
                "Реализуйте `throttle(fn, limit)`.\n\n"
                "Возвращает обёртку, которая вызывает `fn` не чаще одного раза "
                "в `limit` миллисекунд, игнорируя промежуточные вызовы."
            ),
            "instruction_en": (
                "Implement `throttle(fn, limit)`.\n\n"
                "Returns a wrapper that calls `fn` at most once every `limit` ms, "
                "ignoring calls that arrive within the interval."
            ),
            "voice_intro_ru": "Открою задание — реализуйте функцию throttle.",
            "voice_intro_en": "I'll open a coding task — implement throttle.",
            "language": "javascript",
            "starter_code": (
                "/**\n"
                " * @param {Function} fn\n"
                " * @param {number} limit - milliseconds\n"
                " * @returns {Function}\n"
                " */\n"
                "function throttle(fn, limit) {\n"
                "  // implement here\n"
                "}\n"
            ),
            "expected_solution": (
                "function throttle(fn, limit) {\n"
                "  let lastCall = 0;\n"
                "  return function(...args) {\n"
                "    const now = Date.now();\n"
                "    if (now - lastCall >= limit) {\n"
                "      lastCall = now;\n"
                "      return fn.apply(this, args);\n"
                "    }\n"
                "  };\n"
                "}\n"
            ),
            "evaluation_rubric": (
                "Tracks last call time (3), enforces limit (4), preserves this/args (2), "
                "clean code (1). Max 10."
            ),
            "examples": [
                {"description": "10 calls in 100ms with limit=200ms → only 1 real call"},
            ],
            "evaluation_criteria": ["Ограничение частоты", "Сохранение контекста", "Разница с debounce"],
            "time_limit_minutes": 8,
        },
    ],

    # ── QA Engineer ──────────────────────────────────────────────────────────
    "qa_engineer": [
        {
            "id": "qa_login_test_cases",
            "difficulty": "junior",
            "task_type": "qa_test_case_task",
            "title_ru": "Тест-кейсы: форма логина",
            "title_en": "Test cases: login form",
            "instruction_ru": (
                "Напишите тест-кейсы для формы логина.\n\n"
                "Поля: Email, Пароль, кнопка «Войти».\n\n"
                "Минимум 6 тест-кейсов (позитивные + негативные). "
                "Формат: ID | Описание | Входные данные | Ожидаемый результат"
            ),
            "instruction_en": (
                "Write test cases for a login form.\n\n"
                "Fields: Email, Password, 'Sign In' button.\n\n"
                "At least 6 test cases (positive + negative). "
                "Format: ID | Description | Input | Expected result"
            ),
            "voice_intro_ru": "Открою задание — тест-кейсы для формы логина.",
            "voice_intro_en": "I'll open a test case task — login form.",
            "language": "text",
            "starter_code": (
                "ID | Описание | Входные данные | Ожидаемый результат\n"
                "---\n"
                "TC-01 | ...\n"
            ),
            "expected_solution": (
                "TC-01 Valid login → success. "
                "TC-02 Wrong password → error message. "
                "TC-03 Empty email → validation error. "
                "TC-04 Empty password → validation error. "
                "TC-05 Invalid email format → validation error. "
                "TC-06 SQL injection in email field → no crash, error message."
            ),
            "evaluation_rubric": (
                "Happy path (1), wrong password (1), empty fields (2), "
                "invalid format (2), security/boundary (2), format compliance (2). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Позитивные сценарии", "Негативные сценарии", "Граничные случаи"],
            "time_limit_minutes": 10,
        },
        {
            "id": "qa_api_test_plan",
            "difficulty": "middle",
            "task_type": "qa_test_case_task",
            "title_ru": "Тест-план для REST API endpoint",
            "title_en": "Test plan for REST API endpoint",
            "instruction_ru": (
                "POST `/api/v1/orders` создаёт заказ.\n\n"
                "Body: `{product_id: int, quantity: int, user_id: int}`\n"
                "Success: 201 + `{order_id, status: 'created'}`\n\n"
                "Напишите API тест-план: минимум 8 случаев. "
                "Укажите HTTP метод, тело запроса, ожидаемый статус и проверки."
            ),
            "instruction_en": (
                "POST `/api/v1/orders` creates an order.\n\n"
                "Body: `{product_id: int, quantity: int, user_id: int}`\n"
                "Success: 201 + `{order_id, status: 'created'}`\n\n"
                "Write an API test plan: at least 8 cases. "
                "Include HTTP method, request body, expected status, and assertions."
            ),
            "voice_intro_ru": "Открою задание — тест-план для API endpoint.",
            "voice_intro_en": "I'll open a task — API test plan.",
            "language": "text",
            "starter_code": (
                "Endpoint: POST /api/v1/orders\n\n"
                "Test 1: ...\n"
                "  Body: ...\n"
                "  Expected: ...\n"
            ),
            "expected_solution": (
                "201 valid body; 400 missing fields; 400 quantity=0; "
                "400 quantity negative; 404 invalid product_id; "
                "401 no auth; 422 wrong types; 429 rate limit."
            ),
            "evaluation_rubric": (
                "Happy path 201 (1), missing required fields (2), boundary qty (2), "
                "auth/security (2), error body structure checked (2), 8+ cases (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Покрытие 4xx", "Auth/Security", "Структура ответа"],
            "time_limit_minutes": 12,
        },
        {
            "id": "qa_bug_report",
            "difficulty": "junior",
            "task_type": "debugging_task",
            "title_ru": "Написать баг-репорт",
            "title_en": "Write a bug report",
            "instruction_ru": (
                "Вы обнаружили: при вводе email с пробелами в форме регистрации "
                "(например `\" user@example.com \"`) форма принимает его как валидный, "
                "но письмо подтверждения не приходит.\n\n"
                "Напишите полный баг-репорт: Summary, Steps to reproduce, "
                "Expected, Actual, Severity, Environment, Suggested fix."
            ),
            "instruction_en": (
                "You found: when entering an email with leading/trailing spaces "
                "(`\" user@example.com \"`) in the registration form, "
                "it's accepted as valid but the confirmation email is never sent.\n\n"
                "Write a complete bug report: Summary, Steps, "
                "Expected, Actual, Severity, Environment, Suggested fix."
            ),
            "voice_intro_ru": "Открою задание — написать баг-репорт по конкретной проблеме.",
            "voice_intro_en": "I'll open a task — write a bug report.",
            "language": "text",
            "starter_code": (
                "Summary: ...\n\n"
                "Steps to reproduce:\n"
                "1. ...\n\n"
                "Expected: ...\n"
                "Actual: ...\n\n"
                "Severity: ...\n"
                "Environment: ...\n\n"
                "Suggested fix: ...\n"
            ),
            "expected_solution": (
                "Summary: Registration accepts email with whitespace but confirmation fails. "
                "Severity: High. Steps: enter ' user@example.com ', submit, no email received. "
                "Fix: trim whitespace before validation and storage."
            ),
            "evaluation_rubric": (
                "Clear summary (2), reproducible steps (2), expected vs actual (2), "
                "correct severity reasoning (2), suggested fix (2). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Steps to reproduce", "Severity обоснована", "Suggested fix"],
            "time_limit_minutes": 8,
        },
    ],

    # ── DevOps Engineer ──────────────────────────────────────────────────────
    "devops_engineer": [
        {
            "id": "devops_docker_compose_bug",
            "difficulty": "junior",
            "task_type": "debugging_task",
            "title_ru": "Анализ Docker Compose конфига",
            "title_en": "Analyze Docker Compose config",
            "instruction_ru": (
                "Ниже Docker Compose конфиг с несколькими проблемами. "
                "Найдите их и опишите как исправить."
            ),
            "instruction_en": (
                "The Docker Compose config below has multiple issues. "
                "Find them and describe the fixes."
            ),
            "voice_intro_ru": "Открою задание — найти проблемы в Docker Compose конфиге.",
            "voice_intro_en": "I'll open a debugging task — find issues in Docker Compose config.",
            "language": "other",
            "starter_code": (
                "version: '3.8'\n"
                "services:\n"
                "  web:\n"
                "    image: myapp:latest\n"
                "    ports:\n"
                "      - '80:80'\n"
                "    environment:\n"
                "      DATABASE_URL: postgres://user:password@db/mydb\n"
                "    depends_on:\n"
                "      - db\n"
                "  db:\n"
                "    image: postgres\n"
                "    volumes:\n"
                "      - ./data:/var/lib/postgresql/data\n"
                "\n"
                "# Analyse: what's wrong? How to fix?\n"
            ),
            "expected_solution": (
                "Missing: POSTGRES_PASSWORD env (db won't start), healthcheck on db "
                "(web may start before db is ready), restart policy, "
                "hardcoded credentials in env (use secrets or .env file)."
            ),
            "evaluation_rubric": (
                "Missing POSTGRES_PASSWORD (2), no healthcheck / depends_on condition (3), "
                "no restart policy (2), credentials security (2), format (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Нашёл все проблемы", "Безопасность credentials", "Healthcheck"],
            "time_limit_minutes": 10,
        },
        {
            "id": "devops_ci_pipeline",
            "difficulty": "middle",
            "task_type": "system_design_task",
            "title_ru": "CI/CD pipeline для Python сервиса",
            "title_en": "CI/CD pipeline for Python service",
            "instruction_ru": (
                "Опишите CI/CD pipeline для Python FastAPI сервиса.\n\n"
                "Этапы на ваш выбор. Покройте:\n"
                "- lint + tests\n"
                "- build Docker image\n"
                "- push to registry\n"
                "- deploy to staging\n"
                "- что нужно для rollback?"
            ),
            "instruction_en": (
                "Describe a CI/CD pipeline for a Python FastAPI service.\n\n"
                "Stages at your discretion. Cover:\n"
                "- lint + tests\n"
                "- build Docker image\n"
                "- push to registry\n"
                "- deploy to staging\n"
                "- what does rollback require?"
            ),
            "voice_intro_ru": "Открою задание — проектирование CI/CD pipeline.",
            "voice_intro_en": "I'll open a design task — CI/CD pipeline.",
            "language": "text",
            "starter_code": (
                "Pipeline stages:\n\n"
                "1. ...\n"
                "2. ...\n\n"
                "Rollback strategy:\n"
            ),
            "expected_solution": (
                "lint→test→build image with git sha tag→push to registry→"
                "deploy to staging via helm/k8s→smoke test→manual approve→prod. "
                "Rollback: redeploy previous image tag."
            ),
            "evaluation_rubric": (
                "lint/test stage (2), docker build + tag strategy (2), "
                "registry push (1), staging deploy (2), rollback plan (3). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Стадии pipeline", "Docker tagging", "Rollback стратегия"],
            "time_limit_minutes": 12,
        },
    ],

    # ── Data Scientist / Analyst ──────────────────────────────────────────────
    "data_scientist": [
        {
            "id": "ds_sql_top_users",
            "difficulty": "junior",
            "task_type": "sql_task",
            "title_ru": "SQL: топ-5 пользователей по выручке",
            "title_en": "SQL: top 5 users by revenue",
            "instruction_ru": (
                "Таблица `orders(user_id, amount, created_at)`.\n\n"
                "Верните топ-5 пользователей по суммарной выручке за последние 30 дней. "
                "Вывести: `user_id`, `total_revenue`. Отсортировать по убыванию."
            ),
            "instruction_en": (
                "Table: `orders(user_id, amount, created_at)`.\n\n"
                "Return top 5 users by total revenue in the last 30 days. "
                "Output: `user_id`, `total_revenue`. Sort descending."
            ),
            "voice_intro_ru": "Открою SQL задание — топ пользователей по выручке.",
            "voice_intro_en": "I'll open a SQL task — top users by revenue.",
            "language": "sql",
            "starter_code": (
                "-- orders(user_id INT, amount DECIMAL, created_at TIMESTAMP)\n\n"
                "SELECT\n"
                "    -- write here\n"
                "FROM orders\n"
                "WHERE ...\n"
                "GROUP BY ...\n"
                "ORDER BY ...\n"
                "LIMIT 5;\n"
            ),
            "expected_solution": (
                "SELECT user_id, SUM(amount) AS total_revenue\n"
                "FROM orders\n"
                "WHERE created_at >= NOW() - INTERVAL '30 days'\n"
                "GROUP BY user_id\n"
                "ORDER BY total_revenue DESC\n"
                "LIMIT 5;\n"
            ),
            "evaluation_rubric": (
                "SUM(amount) (2), 30-day filter (3), GROUP BY (2), DESC + LIMIT 5 (2), alias (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["SUM + GROUP BY", "DATE фильтр", "ORDER + LIMIT"],
            "time_limit_minutes": 10,
        },
        {
            "id": "ds_window_function",
            "difficulty": "middle",
            "task_type": "sql_task",
            "title_ru": "SQL: оконная функция — rank по категории",
            "title_en": "SQL: window function — rank within category",
            "instruction_ru": (
                "Таблица `products(id, name, category, price)`.\n\n"
                "Для каждого продукта верните: `id, name, category, price` и `rank` "
                "(ранг по цене внутри категории, 1 = самый дорогой). "
                "Используйте оконную функцию."
            ),
            "instruction_en": (
                "Table: `products(id, name, category, price)`.\n\n"
                "For each product return: `id, name, category, price`, `rank` "
                "(rank by price within category, 1 = most expensive). "
                "Use a window function."
            ),
            "voice_intro_ru": "Открою SQL задание — оконная функция RANK.",
            "voice_intro_en": "I'll open a SQL task — window function RANK.",
            "language": "sql",
            "starter_code": (
                "-- products(id INT, name TEXT, category TEXT, price DECIMAL)\n\n"
                "SELECT id, name, category, price,\n"
                "    -- add RANK() here\n"
                "FROM products;\n"
            ),
            "expected_solution": (
                "SELECT id, name, category, price,\n"
                "    RANK() OVER (PARTITION BY category ORDER BY price DESC) AS rank\n"
                "FROM products;\n"
            ),
            "evaluation_rubric": (
                "RANK() (2), OVER clause (2), PARTITION BY category (3), "
                "ORDER BY price DESC (2), alias (1). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["RANK() OVER", "PARTITION BY", "ORDER BY"],
            "time_limit_minutes": 10,
        },
    ],

    # ── Product Manager ────────────────────────────────────────────────────────
    "product_manager": [
        {
            "id": "pm_backlog_prioritization",
            "difficulty": "middle",
            "task_type": "product_case_task",
            "title_ru": "Приоритизация бэклога",
            "title_en": "Backlog prioritization",
            "instruction_ru": (
                "5 фич в бэклоге. Приоритизируйте любым фреймворком (RICE / MoSCoW / ICE).\n\n"
                "Фичи: Push-уведомления, Тёмная тема, Оффлайн-режим, "
                "Реферальная программа, Ускорение загрузки (3s → 1s).\n\n"
                "Контекст: B2C мобильное приложение, DAU 50k, retention D30 = 15%."
            ),
            "instruction_en": (
                "Prioritize 5 backlog features using any framework (RICE / MoSCoW / ICE).\n\n"
                "Features: Push notifications, Dark mode, Offline mode, "
                "Referral program, Performance (3s → 1s).\n\n"
                "Context: B2C mobile app, DAU 50k, D30 retention 15%."
            ),
            "voice_intro_ru": "Открою продуктовый кейс — приоритизация бэклога.",
            "voice_intro_en": "I'll open a product case — backlog prioritization.",
            "language": "text",
            "starter_code": (
                "Фреймворк: ...\n\n"
                "Приоритет 1: [фича] — обоснование:\n"
                "Приоритет 2: ...\n"
            ),
            "expected_solution": (
                "Performance > Offline > Push > Referral > Dark mode. "
                "Performance directly impacts retention (D30=15% likely load-related). "
                "Offline increases DAU. Dark mode low impact vs effort."
            ),
            "evaluation_rubric": (
                "Framework applied consistently (3), business reasoning (3), "
                "retention/DAU framing (2), justified order (2). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["Фреймворк", "Бизнес-обоснование", "Retention/DAU фокус"],
            "time_limit_minutes": 12,
        },
        {
            "id": "pm_metrics_definition",
            "difficulty": "middle",
            "task_type": "product_case_task",
            "title_ru": "Метрики для онбординга",
            "title_en": "Metrics for onboarding flow",
            "instruction_ru": (
                "Вы PM мобильного приложения. Онбординг — 5 шагов после регистрации.\n\n"
                "Определите:\n"
                "1. Ключевую метрику успеха онбординга\n"
                "2. 3–5 сопутствующих метрик\n"
                "3. Как узнать, что онбординг 'сломан', не дожидаясь drop в retention?"
            ),
            "instruction_en": (
                "You're PM of a mobile app. Onboarding is 5 steps after registration.\n\n"
                "Define:\n"
                "1. The north-star metric for onboarding success\n"
                "2. 3–5 supporting metrics\n"
                "3. How to detect a 'broken' onboarding before retention drops?"
            ),
            "voice_intro_ru": "Открою продуктовый кейс — метрики онбординга.",
            "voice_intro_en": "I'll open a product case — onboarding metrics.",
            "language": "text",
            "starter_code": (
                "North-star метрика: ...\n\n"
                "Supporting metrics:\n"
                "1. ...\n\n"
                "Ранний сигнал поломки: ...\n"
            ),
            "expected_solution": (
                "North-star: % users completing all 5 steps within 24h. "
                "Supporting: step-by-step drop-off, time-per-step, "
                "D1/D7 retention by cohort, support tickets about onboarding. "
                "Early signal: step 2 drop-off spike before retention data arrives."
            ),
            "evaluation_rubric": (
                "North-star metric (3), 3+ supporting metrics (3), "
                "early signal reasoning (2), metric clarity (2). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["North-star", "Воронка шагов", "Ранний сигнал"],
            "time_limit_minutes": 10,
        },
    ],

    # ── Mobile Engineer ────────────────────────────────────────────────────────
    "mobile_engineer": [
        {
            "id": "mob_lru_cache",
            "difficulty": "middle",
            "task_type": "coding_task",
            "title_ru": "Реализация LRU кэша",
            "title_en": "Implement LRU cache",
            "instruction_ru": (
                "Реализуйте `LRUCache(capacity)` с методами `get(key)` и `put(key, value)`.\n\n"
                "`get` возвращает значение или -1. "
                "При превышении ёмкости вытесняется наименее используемый элемент.\n"
                "Обе операции должны работать за O(1)."
            ),
            "instruction_en": (
                "Implement `LRUCache(capacity)` with `get(key)` and `put(key, value)`.\n\n"
                "`get` returns value or -1. "
                "Evict the least recently used item when capacity is exceeded.\n"
                "Both operations must be O(1)."
            ),
            "voice_intro_ru": "Открою задание — реализация LRU кэша за O(1).",
            "voice_intro_en": "I'll open a coding task — LRU cache with O(1) operations.",
            "language": "python",
            "starter_code": (
                "class LRUCache:\n"
                "    def __init__(self, capacity: int):\n"
                "        self.capacity = capacity\n"
                "        # implement here\n\n"
                "    def get(self, key: int) -> int:\n"
                "        # return value or -1\n"
                "        pass\n\n"
                "    def put(self, key: int, value: int) -> None:\n"
                "        # insert/update key-value pair\n"
                "        pass\n"
            ),
            "expected_solution": (
                "from collections import OrderedDict\n"
                "class LRUCache:\n"
                "    def __init__(self, capacity):\n"
                "        self.cap = capacity; self.cache = OrderedDict()\n"
                "    def get(self, key):\n"
                "        if key not in self.cache: return -1\n"
                "        self.cache.move_to_end(key); return self.cache[key]\n"
                "    def put(self, key, value):\n"
                "        if key in self.cache: self.cache.move_to_end(key)\n"
                "        self.cache[key] = value\n"
                "        if len(self.cache) > self.cap: self.cache.popitem(last=False)\n"
            ),
            "evaluation_rubric": (
                "O(1) get/put (3), correct eviction of LRU (4), "
                "get returns -1 for miss (2), capacity check (1). Max 10."
            ),
            "examples": [
                {"input": "capacity=2; put(1,1); put(2,2); get(1)→1; put(3,3); get(2)→?", "output": "get(2) = -1 (evicted)"},
            ],
            "evaluation_criteria": ["O(1) операции", "Правильное вытеснение", "Корректный get"],
            "time_limit_minutes": 12,
        },
        {
            "id": "mob_image_loading",
            "difficulty": "senior",
            "task_type": "system_design_task",
            "title_ru": "Дизайн загрузки изображений в ленте",
            "title_en": "Image loading strategy for a feed",
            "instruction_ru": (
                "В мобильном приложении есть лента с изображениями (Instagram-like).\n\n"
                "Опишите стратегию:\n"
                "1. Кэширование изображений (memory + disk)\n"
                "2. Prefetch/lazy load\n"
                "3. Placeholder пока грузится\n"
                "4. Что делать при slow/offline connection?"
            ),
            "instruction_en": (
                "Mobile app has an image feed (Instagram-like).\n\n"
                "Describe your strategy:\n"
                "1. Image caching (memory + disk)\n"
                "2. Prefetch / lazy loading\n"
                "3. Placeholder while loading\n"
                "4. How to handle slow / offline connections?"
            ),
            "voice_intro_ru": "Открою задание — дизайн загрузки изображений в ленте.",
            "voice_intro_en": "I'll open a design task — image loading for a feed.",
            "language": "text",
            "starter_code": (
                "Caching strategy:\n"
                "  Memory: ...\n"
                "  Disk: ...\n\n"
                "Prefetch / lazy load: ...\n\n"
                "Placeholder: ...\n\n"
                "Offline / slow connection: ...\n"
            ),
            "expected_solution": (
                "Memory LRU cache (e.g. 50MB limit), disk cache with TTL. "
                "Lazy load via RecyclerView/FlatList listener, prefetch ±2 items. "
                "BlurHash or color placeholder. Offline: show cached, queue failed. "
                "Slow: progressive JPEG or WebP."
            ),
            "evaluation_rubric": (
                "Two-level cache (3), lazy + prefetch strategy (2), "
                "placeholder approach (2), offline graceful degradation (3). Max 10."
            ),
            "examples": [],
            "evaluation_criteria": ["2-уровневый кэш", "Prefetch стратегия", "Offline поведение"],
            "time_limit_minutes": 12,
        },
    ],
}

# ---------------------------------------------------------------------------
# Hidden fields — must never be serialized to API responses
# ---------------------------------------------------------------------------

_BACKEND_ONLY_FIELDS = frozenset({"expected_solution", "evaluation_rubric"})

# Difficulty ordering for plan selection
_DIFFICULTY_ORDER = {"junior": 0, "middle": 1, "senior": 2}


def _task_difficulty_score(task: dict) -> int:
    return _DIFFICULTY_ORDER.get(task.get("difficulty", "middle"), 1)


def get_practical_plan(
    role: str,
    seniority: str | None,
    language: str = "ru",
) -> list[str]:
    """
    Returns an ordered list of task IDs for the interview.

    Selection rules:
    - Count is determined by seniority (junior=2, middle=3, senior=4).
    - For junior: prefer difficulty='junior' tasks.
    - For senior: include at least one difficulty='senior' task.
    - No duplicates within one interview.
    - Returns a shuffled-within-level list for variety.
    """
    tasks = TASK_BANK.get(role, [])
    if not tasks:
        return []

    count = TASKS_BY_LEVEL.get(seniority or "junior", 2)

    # Bucket by difficulty
    by_difficulty: dict[str, list[dict]] = {"junior": [], "middle": [], "senior": []}
    for t in tasks:
        diff = t.get("difficulty", "middle")
        by_difficulty.setdefault(diff, []).append(t)

    selected: list[dict] = []

    if seniority == "senior":
        # 1 senior task guaranteed, then fill with middle/junior
        pool_order = ["senior", "middle", "junior"]
    elif seniority == "middle":
        pool_order = ["middle", "junior", "senior"]
    else:
        # junior or unknown
        pool_order = ["junior", "middle", "senior"]

    pool: list[dict] = []
    seen_ids: set[str] = set()
    for diff in pool_order:
        shuffled = list(by_difficulty.get(diff, []))
        random.shuffle(shuffled)
        for t in shuffled:
            tid = t.get("id", "")
            if tid and tid not in seen_ids:
                pool.append(t)
                seen_ids.add(tid)

    selected = pool[:count]
    return [t["id"] for t in selected]


def get_task_by_id(task_id: str, role: str) -> dict | None:
    """Lookup a task by its stable ID within a role's bank."""
    for task in TASK_BANK.get(role, []):
        if task.get("id") == task_id:
            return task
    return None


def get_task_for_frontend(task: dict, language: str = "ru") -> dict:
    """
    Strip all backend-only fields and return a frontend-safe dict.
    Adds a fresh task_id (UUID) for submission tracking.
    """
    lang = language if language in ("ru", "en") else "ru"
    title_key = f"title_{lang}"
    instruction_key = f"instruction_{lang}"
    voice_intro_key = f"voice_intro_{lang}"

    return {
        "task_id": str(uuid.uuid4()),
        "stable_id": task.get("id", ""),        # backend stable reference
        "task_type": task["task_type"],
        "title": task.get(title_key) or task.get("title_en") or task.get("title_ru", ""),
        "instruction": task.get(instruction_key) or task.get("instruction_en") or task.get("instruction_ru", ""),
        "voice_intro": task.get(voice_intro_key) or task.get("voice_intro_ru"),
        "language": task.get("language"),
        "starter_code": task.get("starter_code"),
        "examples": task.get("examples", []),
        "evaluation_criteria": task.get("evaluation_criteria", []),
        "time_limit_minutes": task.get("time_limit_minutes", 10),
        # expected_solution and evaluation_rubric are intentionally omitted
    }


# ---------------------------------------------------------------------------
# Trigger policy
# ---------------------------------------------------------------------------

def should_trigger_next_practical_task(
    role: str,
    answered_count: int,
    tasks_remaining_in_plan: int,
    tasks_completed_count: int,
    current_stage_key: str | None = None,
) -> bool:
    """
    Returns True when the next practical task from the plan should be triggered.

    Replaces the old boolean already_triggered with a plan-based approach:
    - must have tasks left in the plan
    - role supports practical tasks
    - answered_count is in the window (enough context, not too late)
    - must wait BETWEEN_TASKS_MIN_ANSWERS answers between tasks
    - appropriate stage
    """
    if tasks_remaining_in_plan <= 0:
        return False
    if role not in PRACTICAL_TASK_ROLES:
        return False
    # Need MIN answers total before first task
    if answered_count < MIN_ANSWERS_BEFORE_PRACTICAL:
        return False
    if answered_count > MAX_ANSWERS_BEFORE_PRACTICAL + tasks_completed_count * BETWEEN_TASKS_MIN_ANSWERS:
        return False
    # Between tasks: need at least BETWEEN_TASKS_MIN_ANSWERS answers after last task
    # (This is enforced by the trigger window expansion above and the caller tracking answered_since_last_task)

    stage = (current_stage_key or "").strip().lower()
    if stage and stage not in PRACTICAL_TASK_ALLOWED_STAGES:
        return False
    return True


# ---------------------------------------------------------------------------
# Legacy compat shim (keep old callers working during transition)
# ---------------------------------------------------------------------------

def should_trigger_practical_task(
    role: str,
    answered_count: int,
    already_triggered: bool,
    current_stage_key: str | None = None,
) -> bool:
    """Compatibility wrapper. New code should use should_trigger_next_practical_task."""
    return should_trigger_next_practical_task(
        role=role,
        answered_count=answered_count,
        tasks_remaining_in_plan=0 if already_triggered else 1,
        tasks_completed_count=1 if already_triggered else 0,
        current_stage_key=current_stage_key,
    )


def get_practical_task(role: str, language: str = "ru") -> dict | None:
    """Legacy shim. New code should use get_practical_plan + get_task_by_id + get_task_for_frontend."""
    tasks = TASK_BANK.get(role, [])
    if not tasks:
        return None
    task = random.choice(tasks)
    return get_task_for_frontend(task, language)
