from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import uuid
from collections import Counter
from typing import Any

import httpx


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Origin": os.getenv("TEST_ORIGIN", "http://localhost:3000"),
    }


def _candidate_answer_for_question(question: str, role: str, turn: int) -> str:
    q = (question or "").lower()
    if "не понял" in q or "переформулиру" in q:
        return "Окей, понял. Сначала подниму request id и transaction id, потом сверю API response, логи и статус транзакции в БД."
    if "какие данные" in q:
        return "Соберу request/response, correlation id, transaction id, логи сервиса, статус операции в БД и таймлайн событий."
    if "где искать первопричину" in q or "где будете искать" in q:
        return "Сначала API gateway и сервис платежей по correlation id, затем интеграционный слой с провайдером и уже после фронт."
    if "как проверите фикс" in q:
        return "Прогоню повторный кейс на тестовой среде, проверю idempotency и что соседние платежные сценарии не сломаны в регрессии."
    if "регрес" in q:
        return "Добавлю smoke на payment status mismatch, автопроверку статусов и алерт по рассинхрону между процессингом и приложением."
    if "ci/cd" in q:
        return "Критичные API тесты ставим в pipeline gate, нестабильные тесты отдельно, перед релизом обязательный smoke и ручной чек-лист."
    if "go/no-go" in q:
        return "Go только при нуле blocker дефектов, стабильном smoke, error-rate в норме и подтвержденном rollback-плане."
    if "пример" in q and "кейс" in q:
        return "Был инцидент: деньги списались, статус ошибки. Я координировал разбор, собрали логи и IDs, нашли race condition в интеграции, после фикса инцидент не повторялся."
    if "расскажите о себе" in q or "ваш путь" in q:
        return (
            "Руковожу направлением сопровождения мобильного банка. "
            "Лично веду разбор критичных дефектов, triage с разработкой и контроль качества релизов."
        )
    if "что именно сделали вы лично" in q:
        return "Лично поставил план разбора, задал гипотезы, распределил проверку по команде и согласовал критерии фикса с разработчиками."
    if "результат" in q:
        return "Снизили повторяемость инцидента, ускорили локализацию дефектов и убрали ручные потери при проверке статусов."
    if role == "qa_engineer":
        fallback_answers = [
            "Начинаю с воспроизведения на тестовой среде и фиксации шагов.",
            "Проверяю API контракт, статусы и связность логов по correlation id.",
            "Если ответ слабый, уточняю гипотезу и выбираю самый рискованный путь проверки первым.",
        ]
        return fallback_answers[turn % len(fallback_answers)]
    return "Сначала фиксирую контекст, затем проверяю наиболее рискованный участок и валидирую результат по измеримому сигналу."


def _compute_human_likeness(metrics: dict[str, int]) -> tuple[int, str]:
    repeated = int(metrics.get("repeated_question_count", 0))
    semantic_repeated = int(metrics.get("semantic_repeated_question_count", 0))
    fallback_count = int(metrics.get("fallback_count", 0))
    clarifications = int(metrics.get("clarification_count", 0))
    strategist_success = int(metrics.get("strategist_success_count", 0))
    total_turns = max(1, int(metrics.get("total_turns", 0)))

    score = 10
    score -= min(4, repeated + semantic_repeated)
    score -= min(3, fallback_count)
    score -= 1 if clarifications > total_turns // 2 else 0
    if strategist_success < max(1, int(0.6 * total_turns)):
        score -= 2
    score = max(1, min(10, score))

    if score >= 8:
        verdict = "human-like"
    elif score >= 6:
        verdict = "mixed"
    else:
        verdict = "bot-like"
    return score, verdict


async def _run_smoke(role: str, provider: str, base_url: str, max_turns: int, turn_delay_seconds: float = 20.0) -> int:
    async with httpx.AsyncClient(base_url=base_url, timeout=300.0) as client:
        status_resp = await client.get("/ai/status")
        status_resp.raise_for_status()
        ai_status = status_resp.json()

        email = f"smoke_{uuid.uuid4().hex[:10]}@example.com"
        register_resp = await client.post(
            "/api/v1/auth/candidate/register",
            json={
                "email": email,
                "password": "Testpass123",
                "full_name": "Smoke Candidate",
            },
        )
        if register_resp.status_code not in {200, 201}:
            raise RuntimeError(f"register failed: {register_resp.status_code} {register_resp.text}")

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Testpass123", "account_type": "candidate"},
        )
        login_resp.raise_for_status()
        token = str(login_resp.json().get("access_token") or "")
        if not token:
            raise RuntimeError("login did not return access_token")

        # upload minimal PDF resume
        pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
        resume_resp = await client.post(
            "/api/v1/candidate/resume/upload",
            headers=_auth_headers(token),
            files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
        )
        resume_resp.raise_for_status()

        start_resp = await client.post(
            "/api/v1/interviews/start",
            headers=_auth_headers(token),
            json={"target_role": role, "language": "ru"},
        )
        start_resp.raise_for_status()
        start_data = start_resp.json()
        interview_id = str(start_data["interview_id"])
        current_question = str(start_data.get("current_question") or "")

        turn = 0
        while turn < max_turns and current_question:
            answer = _candidate_answer_for_question(current_question, role, turn)
            print(f"  [turn {turn+1}/{max_turns}] sending answer...", flush=True)
            msg_resp = await client.post(
                f"/api/v1/interviews/{interview_id}/message",
                headers=_auth_headers(token),
                json={"message": answer},
            )
            msg_resp.raise_for_status()
            msg_data = msg_resp.json()
            current_question = str(msg_data.get("current_question") or "")
            turn += 1
            # Pause between turns to respect free-tier rate limits (8 req/min)
            if current_question and turn < max_turns and turn_delay_seconds > 0:
                await asyncio.sleep(turn_delay_seconds)

        trace_resp = await client.get(
            f"/api/v1/interviews/{interview_id}/debug-trace",
            headers=_auth_headers(token),
        )
        trace_resp.raise_for_status()
        trace_data = trace_resp.json()
        traces = list(trace_data.get("traces") or [])
        metrics = dict(trace_data.get("interview_quality_metrics") or {})

    attempts_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    actual_models: Counter[str] = Counter()
    for item in traces:
        model = str(item.get("actual_model_used") or "").strip()
        if model:
            actual_models[model] += 1
        for attempt in list(item.get("provider_attempts") or []):
            m = str((attempt or {}).get("model") or "").strip()
            if m:
                attempts_counter[m] += 1
        for err in list(item.get("provider_errors") or []):
            msg = str(err or "").strip()
            if msg:
                error_counter[msg] += 1

    human_likeness_score, human_likeness_verdict = _compute_human_likeness(metrics)

    summary = {
        "provider_requested": provider,
        "provider_runtime": ai_status.get("provider"),
        "model_runtime": ai_status.get("model"),
        "total_turns": int(metrics.get("total_turns", 0)),
        "scored_questions": int(metrics.get("scored_questions", 0)),
        "strategist_success_count": int(metrics.get("strategist_success_count", 0)),
        "fallback_count": int(metrics.get("fallback_count", 0)),
        "repeated_question_count": int(metrics.get("repeated_question_count", 0)),
        "semantic_repeated_question_count": int(metrics.get("semantic_repeated_question_count", 0)),
        "resume_phase_turns": int(metrics.get("resume_phase_turns", 0)),
        "technical_case_turns": int(metrics.get("technical_case_turns", 0)),
        "pressure_followup_count": int(metrics.get("pressure_followup_count", 0)),
        "clarification_count": int(metrics.get("clarification_count", 0)),
        "human_likeness": human_likeness_score,
        "human_likeness_verdict": human_likeness_verdict,
        "actual_models_used": dict(actual_models),
        "provider_attempts_by_model": dict(attempts_counter),
        "provider_errors": dict(error_counter),
    }

    print("=== INTERVIEW ENGINE V2 SMOKE SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if trace_data.get("live_smoke_summary"):
        print("\n--- live_smoke_summary ---")
        print(trace_data["live_smoke_summary"])

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Interview Engine v2 smoke interview")
    parser.add_argument("--role", default="qa_engineer", help="Role slug (e.g. qa_engineer)")
    parser.add_argument("--provider", default="openai", help="Expected provider name")
    parser.add_argument("--base-url", default=os.getenv("TEST_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--max-turns", type=int, default=14)
    parser.add_argument("--turn-delay", type=float, default=8.0,
                        help="Seconds to wait between turns (for free-tier rate limits). Default: 8")
    args = parser.parse_args()
    return asyncio.run(
        _run_smoke(
            role=str(args.role).strip(),
            provider=str(args.provider).strip(),
            base_url=str(args.base_url).strip(),
            max_turns=max(1, int(args.max_turns)),
            turn_delay_seconds=float(args.turn_delay),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
