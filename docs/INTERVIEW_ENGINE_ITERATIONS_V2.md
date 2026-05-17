# Interview Engine Iterations (Research-Based)

Этот план собран из `deep-research-report.md` и адаптирован под текущую кодовую базу.

## Цель
Сделать интервью:
- структурированным и одинаково управляемым для всех кандидатов,
- адаптивным по сложности по фактическому качеству ответов,
- прозрачным по скорингу и присвоению уровня.

## Итерация 1 (в работе сейчас) — Уровни и базовая управляемость
Статус: `in_progress`

Изменения:
1. Единая display-шкала уровней: `Junior 1-5`, `Middle 1-5`, `Senior 1-5`.
2. Сохранение внутреннего coarse band (`sfia_1..sfia_7`) для калибровки.
3. Простой gating для верхних Senior-уровней по hard/problem-solving/communication.
4. Unit tests на маппинг уровня и gating.

Критерий готовности:
- отчёт стабильно возвращает один из 15 уровней,
- нет «Strong Middle/Strong Senior» в UI,
- тесты на mapping/gating проходят.

## Итерация 2 — Structured flow и role ordering
Статус: `completed`

Изменения:
1. Зафиксировать flow: `intro -> resume -> role-core -> trade-offs/case -> behavioral -> closing`.
2. Для каждой роли задать order блоков (backend, frontend, qa, devops, data, pm, mobile, ux/ui).
3. Лимиты follow-up: максимум 1-2 на основной вопрос, без зацикливания.
4. Sequence tests на порядок блоков.

Критерий готовности:
- интервью не «прыгает» между несвязанными темами,
- QA остаётся в плоскости quality strategy и risk-based thinking.

## Итерация 3 — Config-driven role banks
Статус: `in_progress`

Изменения:
1. Вынести банки вопросов по ролям в конфиг (`role_question_banks/*.yaml|json`).
2. Хранить: `block`, `tier`, `lead_question`, `allowed_probes`, `scored_metrics`, `strong/weak indicators`.
3. Снизить зависимость от «свободной» LLM-генерации.

Критерий готовности:
- изменение вопросов делается через конфиг, а не через переписывание логики.

## Итерация 4 — Рубрика и evidence-first scoring
Статус: `planned`

Изменения:
1. Ввести единую 7-метричную рубрику:
   - technical_depth
   - practical_experience
   - problem_solving
   - communication
   - ownership
   - role_fit
   - growth_potential
2. Перевести итог в `raw score + confidence + display level + sfia band`.
3. Добавить reviewer flags для пограничных кейсов.

Критерий готовности:
- объяснимость уровня по evidence snippets и метрикам.

## Итерация 5 — Guardrails, calibration, analytics
Статус: `planned`

Изменения:
1. Guardrails: запрет на protected traits и псевдосигналы из видео/голоса.
2. Calibration fixtures по ролям и уровням.
3. Метрики качества: repeated question rate, irrelevant question rate, abandonment, override rate.

Критерий готовности:
- качество интервью измеряется и не деградирует после релизов.

## Notes
- Приоритет: consistency + explainability + candidate experience.
- Эвристики и пороги калибруются на ваших реальных интервью после 1-2 недель сбора данных.
