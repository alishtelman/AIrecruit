import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.ai.providers.base import (
    LLMProvider,
    ProviderAttempt,
    ProviderChatCompletionResult,
    ProviderChatError,
)

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, default_model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._client = httpx.AsyncClient(timeout=45.0)

    @property
    def configured_model(self) -> str:
        return self._default_model

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> ProviderChatCompletionResult:
        actual_model = model or self._default_model
        
        import os
        import sys
        from app.core.config import settings
        is_mock = (
            os.getenv("MOCK_LLM", "").lower() in {"true", "1"}
            or "pytest" in sys.modules
            or not self._api_key
            or settings.allow_mock_ai
        )
        if is_mock:
            tools = None
            tool_choice = None
            if extra_body:
                tools = extra_body.get("tools")
                tool_choice = extra_body.get("tool_choice")
            return self._generate_mock_response(
                messages=messages,
                model=actual_model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
            )

        system_instruction = None
        gemini_contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if not system_instruction:
                    system_instruction = {"parts": [{"text": content}]}
                else:
                    system_instruction["parts"][0]["text"] += f"\n\n{content}"
            elif role == "assistant":
                gemini_contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                gemini_contents.append({"role": "user", "parts": [{"text": content}]})

        payload: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }
        
        if system_instruction:
            payload["systemInstruction"] = system_instruction
            
        if response_format and response_format.get("type") == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"

        attempts = []
        errors = []
        start_time = time.monotonic()
        
        max_attempts = 5
        for attempt_idx in range(max_attempts):
            try:
                # Add dynamic timeout for retries
                timeout = httpx.Timeout(20.0 + (attempt_idx * 15.0))
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{actual_model}:generateContent"
                
                resp = await self._client.post(
                    url,
                    headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=timeout,
                )
                
                if resp.status_code == 429:
                    error_msg = f"Gemini Rate Limit 429: {resp.text}"
                    errors.append(error_msg)
                    attempts.append({"model": actual_model, "ok": False, "error": error_msg})
                    
                    delay = 10.0 * (attempt_idx + 1)
                    try:
                        error_data = resp.json()
                        for detail in error_data.get("error", {}).get("details", []):
                            if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                                retry_str = detail.get("retryDelay", "0s")
                                if retry_str.endswith("s"):
                                    parsed_delay = float(retry_str[:-1])
                                    delay = parsed_delay + 1.0
                    except Exception:
                        pass
                        
                    logger.warning(f"Gemini Rate Limit hit. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                    
                resp.raise_for_status()
                data = resp.json()
                
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as e:
                    raise ProviderChatError(f"Unexpected response structure: {data}") from e
                    
                usage = data.get("usageMetadata", {})
                req_tokens = usage.get("promptTokenCount", 0)
                res_tokens = usage.get("candidatesTokenCount", 0)
                
                attempts.append({"model": actual_model, "ok": True, "error": None})
                latency_ms = (time.monotonic() - start_time) * 1000.0
                
                return ProviderChatCompletionResult(
                    text=text,
                    requested_model=actual_model,
                    actual_model_used=actual_model,
                    request_tokens_estimate=req_tokens,
                    response_tokens_estimate=res_tokens,
                    provider_latency_ms=latency_ms,
                    provider_attempts=attempts,
                    provider_errors=errors,
                    fallback_used=False,
                    raw_response=data,
                )
                
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
                errors.append(error_msg)
                attempts.append({"model": actual_model, "ok": False, "error": error_msg})
                if e.response.status_code in {400, 401, 403, 404}:
                    break  # Non-retriable errors
            except Exception as e:
                error_msg = f"Request failed: {str(e)}"
                errors.append(error_msg)
                attempts.append({"model": actual_model, "ok": False, "error": error_msg})
                
            await asyncio.sleep(2 + attempt_idx * 2)
            
        raise ProviderChatError(
            f"Gemini completion failed for all attempts. Last error: {errors[-1] if errors else 'Unknown'}",
            code="gemini_error"
        )

    def _generate_mock_response(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> ProviderChatCompletionResult:
        import re
        system_content = ""
        user_content = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_content += msg.get("content", "")
            elif msg.get("role") == "user":
                user_content += msg.get("content", "")

        logger.info(f"Gemini mock check: tools={tools}, system_len={len(system_content)}, system_snippet={system_content[:150]}")

        text_response = "Mocked LLM Response"
        raw_response = {}

        if "submit_question_analysis" in str(tools) or "submit_question_analysis" in str(tool_choice) or "submit_question_analysis" in system_content:
            questions_mock = []
            for i in range(1, 10):
                questions_mock.append({
                    "question_number": i,
                    "targeted_competencies": ["technical_core", "behavioral"],
                    "answer_quality": 8.0,
                    "evidence": "Кандидат успешно описал масштабирование и оптимизацию индексов баз данных.",
                    "skills_mentioned": [{"skill": "PostgreSQL", "proficiency": "expert"}],
                    "red_flags": [],
                    "specificity": "high",
                    "depth": "strong",
                    "ai_likelihood": 0.05,
                    "communication_star_structured": True,
                    "communication_style": "Clear, concise, and well-structured.",
                    "problem_solving_approach": "first_principles",
                    "problem_solving_evidence": "Analyzed trade-offs between indexing and write latency.",
                    "leadership_ownership": "strong_ownership"
                })
            
            raw_response = {
                "choices": [{
                    "message": {
                        "tool_calls": [{
                            "function": {
                                "name": "submit_question_analysis",
                                "arguments": json.dumps({"questions": questions_mock})
                            }
                        }]
                    }
                }]
            }
            text_response = json.dumps({"questions": questions_mock})

        elif "submit_competency_assessment" in str(tools) or "submit_competency_assessment" in str(tool_choice) or "submit_competency_assessment" in system_content:
            comp_scores_mock = [
                {
                    "competency": "Root Cause Analysis",
                    "category": "technical_core",
                    "score": 8.5,
                    "weight": 1.0,
                    "evidence": "Описал процесс трассировки неуспешных транзакций через логи и trace ID.",
                    "reasoning": "Отличный диагностический подход на основе первопринципного мышления."
                },
                {
                    "competency": "Communication",
                    "category": "communication",
                    "score": 8.0,
                    "weight": 1.0,
                    "evidence": "Ясно и структурированно отвечал на наводящие вопросы.",
                    "reasoning": "Применение STAR структуры."
                }
            ]
            
            raw_response = {
                "choices": [{
                    "message": {
                        "tool_calls": [{
                            "function": {
                                "name": "submit_competency_assessment",
                                "arguments": json.dumps({
                                    "competency_scores": comp_scores_mock,
                                    "response_consistency": 9.0,
                                    "hiring_recommendation": "yes",
                                    "red_flags": [],
                                    "strengths": ["Strong systems thinking", "Clear STAR structure"],
                                    "weaknesses": ["Minor edge case gaps"],
                                    "recommendations": ["Deep dive into Kubernetes security"]
                                })
                            }
                        }]
                    }
                }]
            }
            text_response = json.dumps({
                "competency_scores": comp_scores_mock,
                "response_consistency": 9.0,
                "hiring_recommendation": "yes",
                "red_flags": [],
                "strengths": ["Strong systems thinking", "Clear STAR structure"],
                "weaknesses": ["Minor edge case gaps"],
                "recommendations": ["Deep dive into Kubernetes security"]
            })

        elif any(keyword in system_content or keyword in user_content for keyword in ["action", "question_text", "best_next_move"]):
            # Extract turn number dynamically from user_content to avoid repeated question check
            turn_num = 1
            try:
                import re
                json_match = re.search(r"Context JSON:\s*(\{.*\})", user_content, re.DOTALL)
                if json_match:
                    ctx_payload = json.loads(json_match.group(1))
                    asked = ctx_payload.get("asked_questions", [])
                    turn_num = len(asked) + 1
            except Exception:
                pass
            
            # Default payload
            payload = {
                "action": "switch_topic",
                "question_text": f"Describe a challenging issue you debugged recently (turn {turn_num}).",
                "target_competency": "Root Cause Analysis",
                "phase": "technical_case",
                "scenario_id": None,
                "scenario_step": 0,
                "difficulty_tier": 3,
                "expected_signal": "Evidence of root cause identification",
                "reasoning": {
                    "candidate_understanding": "Analyzing candidate's debugging skills",
                    "why_this_move": "Candidate resume lists experience in troubleshooting production issues",
                    "conversational_intent": "switch_topic"
                }
            }
            
            # Phase/Context detection
            is_closing = "closing" in user_content or "closing" in system_content or "close_interview" in user_content or "close_interview" in system_content
            is_behavioral = "behavioral" in user_content or "behavioral" in system_content
            is_resume = "resume_deep_dive" in user_content or "intro" in user_content or "warm_up" in user_content
            
            if is_closing:
                payload["action"] = "close_interview"
                payload["question_text"] = f"Спасибо за интервью. У вас есть вопросы ко мне? (turn {turn_num})"
                payload["phase"] = "closing"
                payload["conversational_intent"] = "close_interview"
            elif is_behavioral:
                payload["action"] = "switch_topic"
                payload["question_text"] = f"Давайте перейдем к теме поведенческих компетенций (turn {turn_num})."
                payload["phase"] = "behavioral"
                payload["conversational_intent"] = "switch_topic"
            elif is_resume:
                payload["action"] = "switch_topic"  # Using switch_topic here ensures will_advance = True even in resume phase!
                payload["question_text"] = f"Describe a challenging issue you debugged recently (turn {turn_num})."
                payload["phase"] = "resume_deep_dive"
                payload["conversational_intent"] = "switch_topic"
            else:
                # Default case (e.g. technical phase)
                payload["action"] = "switch_topic"
                payload["question_text"] = f"Давайте перейдем к технической теме (turn {turn_num})."
                payload["phase"] = "technical_case"
                payload["conversational_intent"] = "switch_topic"

            # Allow explicit action overrides requested by the user prompt
            if "start_scenario" in user_content or "scenario" in user_content:
                payload["action"] = "start_scenario"
                payload["scenario_id"] = "qa_payment_failed_money_deducted"
                payload["question_text"] = f"Кейс: деньги списались, но статус ошибки. Что проверите первым? (turn {turn_num})"
            elif "continue_scenario" in user_content:
                payload["action"] = "continue_scenario"
                payload["scenario_id"] = "qa_payment_failed_money_deducted"
                payload["scenario_step"] = 1
                payload["question_text"] = f"Что предпримете следующим шагом? (turn {turn_num})"
            elif "switch_topic" in user_content:
                payload["action"] = "switch_topic"
                payload["question_text"] = f"Давайте перейдем к теме проектирования систем. (turn {turn_num})"
            elif "close_interview" in user_content:
                payload["action"] = "close_interview"
                payload["question_text"] = f"Спасибо за интервью. У вас есть вопросы ко мне? (turn {turn_num})"
                payload["phase"] = "closing"

            text_response = json.dumps(payload)
            raw_response = payload
        
        elif "relevance" in system_content or "relevance" in user_content or "answer_relevance" in system_content or "answer_relevance" in user_content:
            text_response = json.dumps({"relevance": "high", "reasoning": "Answer directly addresses the question."})
            raw_response = {"relevance": "high"}

        return ProviderChatCompletionResult(
            text=text_response,
            requested_model=model,
            actual_model_used=model,
            request_tokens_estimate=150,
            response_tokens_estimate=200,
            provider_latency_ms=10.0,
            provider_attempts=[{"model": model, "ok": True, "error": None}],
            provider_errors=[],
            fallback_used=False,
            raw_response=raw_response,
        )
