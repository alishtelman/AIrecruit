# UX Audit Report — AI HR Frontend Redesign

Дата: 2026-06-16
Контекст: ревизия frontend UX после редизайна в сторону premium SaaS reference (`AI HR.zip`).
Важно: рабочее дерево уже содержало большой набор изменений до этой ревизии; ниже отдельно перечислены проблемы и патчи, проверенные в рамках текущего UX-аудита.

## 1. Проверенные зоны

### Public / Landing / Shared
- Landing page `/`
- Locale switcher
- Not found page `/en` / invalid routes
- Shared shell/header/sidebar patterns
- Auth shell patterns

### Auth
- Candidate login/register
- Company login/register
- Admin login
- Role-aware redirects по коду `useAuth` и login pages
- Logout actions in sidebars/workspace headers

### Candidate
- Candidate dashboard
- Candidate profile/resume/reports на уровне navigation/state patterns
- Interview start
- Interview live page `candidate/interview/[id]`
- Voice-only answer controls
- Transcript review controls
- Practical task modal
- Candidate share page

### Company
- Company dashboard
- Candidate list pagination/filter composition
- Employees / assessment invite flow
- Templates/team/settings/reports на уровне shell/actions patterns
- Company report detail top summary

### Admin
- Admin dashboard
- Admin users/companies/interviews/reports/settings/audit pages на уровне shell/actions/state patterns
- Admin workspace header logout/navigation

## 2. Найденные UX-проблемы

### Critical / High
1. **Language switch ломал route**
   При смене языка URL мог становиться `/en`, что при `localePrefix: "never"` приводило на 404.

2. **Practical task editor был предзаполнен `starter_code`**
   Это смешивало readonly boilerplate и фактический ответ кандидата. По UX кандидат мог случайно отправить шаблон как решение.

3. **Practical modal можно было “пропустить” с потерей задания**
   Кнопка закрытия очищала `practicalTask` и `practicalAnswer`, после чего у кандидата не было очевидного способа вернуться к practical task.

4. **Обычные voice/text answer controls оставались доступны при незавершённом practical task**
   Это позволяло потенциально обойти practical task и продолжить интервью другим ответом.

5. **Logout buttons в shell/header были без явного `type="button"` и `aria-label`**
   При переиспользовании рядом с формами такие кнопки потенциально могут вести себя как submit, а icon/compact UX хуже для accessibility.

6. **`useAuth` мог лишний раз вызывать auth-check из-за inline `allowedRoles` arrays**
   Вызовы вроде `useAuth({ allowedRoles: ["candidate"] })` создают новый массив на render, что может провоцировать лишние запросы/redirect churn.

### Medium
1. Voice-only режим в целом спрятал text fallback за `NEXT_PUBLIC_ALLOW_TEXT_FALLBACK`, но история чата и fallback controls требуют ручного smoke на реальном interview id.
2. Company/admin pages уже в новом shell, но тяжёлые таблицы всё ещё частично зависят от bridge CSS; для “pixel-perfect” нужен отдельный дизайн-pass таблиц.
3. Backend тестовый запуск по документационной команде внутри backend-контейнера использует `localhost:8001`, что недоступно из самого контейнера; требуется `TEST_BASE_URL=http://api-gateway:8080` или запуск с хоста.

## 3. Что исправлено

### Locale / navigation
- `LocaleSwitcher` теперь не делает route replace через locale-aware navigation с URL-prefix.
- Переключатель ставит `NEXT_LOCALE`, очищает случайный `/en`/`/ru` prefix и обновляет текущий путь без ухода на 404.
- Browser smoke подтвердил: `/` после клика `ru/en` остаётся `/`, не `/en`.

### Practical task UX
- `starter_code` больше не попадает в поле ответа.
- `starter_code` показывается отдельным readonly reference block: “Boilerplate / reference”.
- Ответ начинается пустым.
- Отправка disabled, если answer пустой или равен starter code.
- При попытке отправить только boilerplate показывается ошибка прямо внутри modal.
- Ошибка очищается при редактировании ответа.
- Закрытие modal больше не уничтожает задание/черновик.
- Если modal закрыт, появляется карточка “Практическое задание” с CTA “Открыть задание”.
- Пока practical task не отправлен, обычные answer controls скрыты, чтобы нельзя было обойти practical.
- `Escape` закрывает practical modal безопасно: draft сохраняется.

### Logout / shared buttons / accessibility
- Sidebar logout buttons получили `type="button"` и `aria-label`:
  - Candidate shell
  - Company shell
  - Admin shell
- Workspace header logout buttons получили `type="button"` и `aria-label`:
  - Company workspace header
  - Admin workspace header

### Auth guard stability
- `useAuth` теперь использует стабильный `allowedRolesKey`, а не массив в dependency array.
- Это снижает риск лишних `/me` calls и redirect jitter после редизайна shell/layout.

## 4. Проверенные кнопки/actions

### Проверено кодом
- Locale switcher: `en`, `ru`
- Logout: candidate/company/admin sidebar
- Logout: company/admin workspace header
- Interview: replay question
- Interview: start answer / finish answer / transcribing / transcript confirm
- Interview: show/close chat history
- Interview: practical open/close/submit
- Interview: practical modal escape close
- Company dashboard: tabs, filters, pagination, shortlist actions на уровне code path
- Company employees: create invite flow, copy/open invite actions на уровне code path
- Company report: back, collapsed timeline toggle, question accordion на уровне code path

### Проверено live-smoke в браузере
- Landing `/` opens.
- Locale buttons are present as accessible buttons `en` / `ru`.
- Clicking `ru` and `en` keeps URL as `/`, no `/en` 404.
- Candidate share URL did not redirect to locale-prefixed 404 during smoke.

## 5. Validation results

### Frontend
- `docker compose exec -T frontend npm run lint` — PASS
- `docker compose exec -T frontend npm run build` — PASS
- Frontend package has no `npm test` script, so no frontend unit test command exists currently.

### Backend
- `docker compose exec -T backend pytest -q` — FAIL in current docker execution context.
  - Dominant failure category: `httpx.ConnectError: All connection attempts failed`.
  - Cause observed: tests default to `TEST_BASE_URL=http://localhost:8001`; from inside the backend container, `localhost:8001` is not the host gateway.
- Retried with `TEST_BASE_URL=http://api-gateway:8080`:
  - Tests started and progressed past connection errors.
  - Full suite became long-running and was stopped from this audit cycle before final summary.
  - Partial output showed real existing failures (`F`) unrelated to current frontend UX patch; needs separate backend test cleanup pass.

## 6. Known risks

1. **Full backend suite not green in this session**
   Needs separate backend validation pass with correct `TEST_BASE_URL` and investigation of practical-task expectation failures.

2. **Manual full voice E2E still required**
   Need a real authenticated candidate interview id with microphone permission to verify:
   - AI speaking
   - start answer
   - stop answer
   - STT transcript
   - confirm transcript
   - next question
   - finish/report

3. **Practical modal requires live scenario QA**
   Code now prevents bypass/loss, but must manually verify real task payloads for frontend/backend contract.

4. **Bridge CSS is effective but not pixel-perfect**
   Company/admin heavy pages are MVP-consistent, but tables/reports could still be manually redesigned later into reusable Table/Card primitives.

5. **Responsive QA not fully completed visually**
   Code-level audit covered layout patterns; still need browser visual pass at 1920, 1440, 1366, tablet, mobile.

## 7. Manual QA checklist before pilot

### Public/Auth
- Open `/`, switch `ru/en`, verify URL does not become `/ru` or `/en`.
- Candidate login with candidate account → candidate dashboard.
- Candidate login with company/admin account → safe role error.
- Company login with company account → company dashboard.
- Admin login with admin account → admin dashboard.
- Logout for each role → correct login route; browser back does not expose protected content.

### Candidate voice interview
- Start interview from candidate dashboard.
- Confirm no text mode appears unless `NEXT_PUBLIC_ALLOW_TEXT_FALLBACK=true`.
- Click “Начать ответ” → recording starts.
- Click “Завершить ответ” → transcript appears.
- Edit transcript → confirm/send.
- Double-click confirm/send → only one answer sent.
- Microphone denied → retry/error, not silent switch to text chat.
- Finish interview → report generation screen → candidate report.

### Practical task
- Trigger practical task.
- Verify editor starts empty.
- Verify starter code appears only in readonly reference block.
- Try submitting empty answer → disabled.
- Try submitting exact starter code → blocked with inline error.
- Close modal → draft/task persists and “Открыть задание” is visible.
- Reopen modal → draft still present.
- Submit valid answer → modal closes and next interview step appears.

### Company
- Dashboard filters/search/pagination.
- Candidate report open.
- Employees: create invite, copy invite, open invite.
- Templates: create/edit/delete with confirmation where destructive.
- Team/settings: save states and readonly/member role behavior.

### Admin
- Dashboard metrics load.
- Users/companies/interviews tables load.
- Debug/internal reports only visible to admin.
- Admin logout works.

## 8. Files changed in this UX audit pass

- `frontend/src/components/locale-switcher.tsx`
- `frontend/src/components/candidate-shell.tsx`
- `frontend/src/components/company-shell.tsx`
- `frontend/src/components/admin-shell.tsx`
- `frontend/src/components/company-workspace-header.tsx`
- `frontend/src/components/admin-workspace-header.tsx`
- `frontend/src/hooks/useAuth.ts`
- `frontend/src/app/(candidate)/candidate/interview/[id]/page.tsx`
- `ux_audit_report.md`

## 9. Recommendation

Frontend is closer to pilot-ready after these UX fixes: the most dangerous candidate-facing practical task dead-end is fixed, locale switch no longer breaks navigation, logout controls are safer, and voice-only remains the default with text fallback hidden behind env flag.

Before real client pilot, run one manual full voice E2E and one practical-task E2E with screen sizes `1366x768` and mobile width. Separately, clean up backend test configuration/failures so CI confidence matches frontend readiness.
