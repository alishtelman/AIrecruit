"""
AI Interviewer module.

Current implementation: mock with role-based question templates.
Phase 5 replacement: swap MockInterviewer with LLMInterviewer that calls Claude API.
The public interface (get_next_question + InterviewContext) stays the same.
"""
from dataclasses import dataclass, field

MAX_QUESTIONS = 8

# Role-based question banks. Each list has exactly MAX_QUESTIONS entries.
_QUESTIONS: dict[str, list[str]] = {
    "backend_engineer": [
        "Tell me about yourself and your background as a backend engineer.",
        "Describe the most complex system you have built or contributed to. What were the key architectural decisions?",
        "How do you approach database design for a high-traffic application? Walk me through your thought process.",
        "Explain how you handle errors, retries, and failures in production services.",
        "Describe your experience with asynchronous or event-driven architectures. Give a concrete example.",
        "How do you ensure security in the APIs and services you build?",
        "What is your approach to performance profiling and optimization?",
        "How do you balance technical debt against shipping new features? Give a real example.",
    ],
    "qa_engineer": [
        "Tell me about yourself and your experience in quality assurance.",
        "Describe your approach to building a test strategy for a new product feature.",
        "What is your experience with test automation? Which frameworks have you used and why?",
        "How do you decide which test cases to automate versus test manually?",
        "Describe a critical bug you found that prevented a production incident. How did you find it?",
        "How do you handle situations where developers push back on your bug reports?",
        "What is your experience with performance and load testing?",
        "How do you maintain quality in an agile environment with short release cycles?",
    ],
    "product_manager": [
        "Tell me about yourself and your experience as a product manager.",
        "Walk me through how you define and prioritize a product roadmap.",
        "Describe a product you took from idea to launch. What were the key decisions you made?",
        "How do you gather and validate user requirements? Give a specific example.",
        "How do you measure the success of a feature after launch?",
        "Describe a time you had to say no to a stakeholder request. How did you handle it?",
        "How do you collaborate with engineering to ensure timely, high-quality delivery?",
        "Give an example of a data-driven product decision you made.",
    ],
}

_DEFAULT_ROLE = "backend_engineer"


@dataclass
class InterviewContext:
    target_role: str
    question_number: int  # 1-based: which question to generate next
    message_history: list[dict] = field(default_factory=list)
    # Each dict: {"role": "assistant"|"candidate", "content": str}


class MockInterviewer:
    """
    Returns pre-written questions by role and question index.

    TO REPLACE IN PHASE 5:
    - Inject Anthropic client
    - Build a system prompt with role + resume context
    - Pass message_history as conversation turns
    - Return Claude's response as the next question
    """

    async def get_next_question(self, ctx: InterviewContext) -> str:
        questions = _QUESTIONS.get(ctx.target_role, _QUESTIONS[_DEFAULT_ROLE])
        idx = ctx.question_number - 1  # question_number is 1-based
        if 0 <= idx < len(questions):
            return questions[idx]
        return "Is there anything else you would like to share about your experience?"


# Module-level singleton — replace with LLMInterviewer(client=anthropic_client) in Phase 5
interviewer = MockInterviewer()
