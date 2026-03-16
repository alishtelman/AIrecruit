"""
Calibration module — Behaviorally Anchored Rating Scales (BARS) for LLM assessment.

Scientific basis:
  - BARS methodology (Smith & Kendall, 1963) — most reliable rating format in I/O psychology
  - Reduces leniency bias, central tendency, and halo effect in structured interviews
  - Each anchor describes observable, concrete behaviors at each score level

Usage:
  Inject BARS into the Pass 2 assessor prompt to force the LLM to use the full 1-10 scale
  and anchor scores to observable evidence rather than general impressions.
"""

# ---------------------------------------------------------------------------
# Universal scoring anchors (cross-competency)
# Applied to ALL competencies — forces full scale usage
# ---------------------------------------------------------------------------

UNIVERSAL_ANCHORS = """
## CALIBRATION SCALE — Behaviorally Anchored Rating Scales (BARS)

**CRITICAL RULE: Most candidates score 4–7. Reserve 8–10 ONLY for exceptional responses with concrete evidence. Reserve 1–3 for clear deficiencies or incorrect understanding.**

### Score 1–2 — No Competency Demonstrated
- Cannot explain the concept or gives a fundamentally incorrect answer
- Confuses basic terminology
- Example: Asked about database indexing, says "indexes are like bookmarks in Word"

### Score 3–4 — Surface / Textbook Level
- Defines the concept correctly but only from memory, no practical experience
- Cannot describe a real situation where they applied this
- Generic answer without specific technologies, numbers, or trade-offs
- Example: "Indexing speeds up queries. You put an index on columns you query often."

### Score 5–6 — Working Knowledge
- Describes practical usage from real experience, but limited to basic cases
- Mentions specific tools/technologies they used
- Cannot discuss edge cases, failure modes, or advanced trade-offs
- Example: "We added a B-tree index on user_id. It made the query go from 2s to 100ms. I haven't dealt with partial indexes or covering indexes."

### Score 7–8 — Strong Practitioner
- Discusses specific situations with concrete metrics (latency, throughput, scale)
- Explains trade-offs they considered and WHY they made specific decisions
- Mentions edge cases, failure modes, and lessons learned
- Example: "At 50M rows, a single B-tree index wasn't enough. I used a composite index on (user_id, created_at DESC) with INCLUDE to cover the SELECT columns. We also added a partial index for is_active=true rows which cut index size by 60%. We ran EXPLAIN ANALYZE before/after."

### Score 9–10 — Expert / Original Thinking
- Demonstrates deep understanding of internals and underlying mechanisms
- Proactively identifies constraints and limitations not asked about
- Proposes alternatives and explains exactly when each is appropriate
- Shows system-level thinking: how this interacts with other components
- Example (same topic): Above + "The problem with naive indexing at that scale is write amplification — every INSERT/UPDATE rebuilds N indexes. We moved hot-path analytics to a read replica and designed the index strategy around the query plan, not the data model. We also considered BRIN indexes for time-series data given sequential insertion patterns..."

---
## ANTI-PATTERNS TO AVOID (rating errors):

**Leniency bias**: Do NOT give 7+ unless you have quoted evidence of specificity and trade-off reasoning.
**Halo effect**: Score EACH competency independently. A strong answer on Q1 does NOT raise scores for other competencies.
**Central tendency**: Do NOT cluster scores at 5-6. Differentiate clearly between candidates who give examples vs. those who don't.
**Recency bias**: Weight evidence from ALL questions, not just the most recent answer.
"""

# ---------------------------------------------------------------------------
# Category-specific BARS (injected when relevant competency is scored)
# ---------------------------------------------------------------------------

CATEGORY_ANCHORS: dict[str, str] = {
    "technical_core": """
### Technical Core — Differentiation Criteria
Score 3-4 (surface): Names the right tools, cannot explain when NOT to use them
Score 5-6 (working): Built something with this, but in a guided/tutorial context
Score 7-8 (strong): Made architectural decisions, dealt with production failures
Score 9-10 (expert): Can explain the internals, contributed to the tool/pattern, teaches others
""",

    "problem_solving": """
### Problem Solving — Differentiation Criteria
Score 3-4 (surface): Describes a theoretical approach ("I would check logs, then...")
Score 5-6 (working): Describes a real incident but solved it by trial and error
Score 7-8 (strong): Has a systematic methodology, isolated variables, formed hypotheses
Score 9-10 (expert): Prevented similar issues systemically, improved tooling/monitoring as a result
""",

    "communication": """
### Communication — Differentiation Criteria
Score 3-4 (surface): Uses jargon without checking if the listener understands
Score 5-6 (working): Can explain concepts but requires prompting for clarity
Score 7-8 (strong): Structures answers (problem → solution → outcome), uses analogies appropriately
Score 9-10 (expert): Adapts communication level in real-time, builds shared mental models, extremely concise
""",

    "behavioral": """
### Behavioral — Differentiation Criteria
Score 3-4 (surface): Uses "we" without clarifying personal contribution; vague "I helped the team"
Score 5-6 (working): Clear personal contribution, but no reflection on what they'd do differently
Score 7-8 (strong): Specific personal impact with measurable outcomes, honest about failure mode
Score 9-10 (expert): Changed the process/team/culture as a result; systemic thinker about people problems
""",

    "technical_breadth": """
### Technical Breadth — Differentiation Criteria
Score 3-4 (surface): Aware the technology exists, heard about it in a course/article
Score 5-6 (working): Used it once in a project, knows the basics
Score 7-8 (strong): Integrated it in production, knows the gotchas
Score 9-10 (expert): Made architectural decisions about when to use/not use this; evaluated alternatives
""",
}

# ---------------------------------------------------------------------------
# Few-shot calibration examples (2 per competency category)
# Grounded in realistic interview Q&A pairs
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES = """
## FEW-SHOT CALIBRATION EXAMPLES

### Example 1 — technical_core: System Design
Q: "Design a URL shortener like bit.ly that handles 10K writes/sec and 100K reads/sec."
POOR answer (score 3): "I'd use a database to store URLs and generate random short codes."
→ Score: 3. No scale reasoning, no read/write split, no cache, no hash collision handling.

STRONG answer (score 8): "At 100K reads/sec, a single DB would be the bottleneck — I'd put Redis in front for hot URLs (80/20 rule). For writes: a distributed ID generator (Snowflake-style) avoids collision without DB round-trips. Base62 encode the ID for the short URL. I'd shard the DB by the first 2 chars of the short code. Replication lag is acceptable since eventual consistency is fine for reads."
→ Score: 8. Addresses scale explicitly, caches hot path, solves collision problem, justifies consistency model.

---
### Example 2 — problem_solving: Debugging
Q: "Tell me about the hardest production bug you've debugged."
POOR answer (score 4): "We had a memory leak. I looked at the logs and found the issue after a few hours."
→ Score: 4. No hypothesis-driven approach, no tools mentioned, no root cause reasoning.

STRONG answer (score 8): "Our service's P99 latency spiked every 6 hours. I added histogram metrics and found it correlated with GC pauses. Heap dumps showed we were retaining 500MB of HTTP client connections — a connection pool wasn't being released on timeout. The fix was wrapping the client in a context manager. I added a metric for open connections to catch this pattern early. We also changed the default timeout policy."
→ Score: 8. Clear hypothesis formation, specific tools (heap dumps, metrics), root cause identified, prevented recurrence.

---
### Example 3 — behavioral: Conflict/Collaboration
Q: "Describe a time you disagreed with a technical decision made by your team."
POOR answer (score 4): "We disagreed about the database choice. I said my opinion but they went with PostgreSQL."
→ Score: 4. No personal reasoning explained, no influence attempt, no outcome reflection.

STRONG answer (score 8): "My lead wanted to add a message queue before we had evidence of the bottleneck. I prepared a load test showing we wouldn't hit the queue limit for 6 months with current growth. I proposed we add instrumentation first so we'd know exactly when to add it. They agreed. 4 months later the metrics showed we needed it, and we had the right data to choose Kafka over RabbitMQ. I learned to make disagreements data-driven rather than opinion-based."
→ Score: 8. Data-driven dissent, influenced outcome, clear personal learning.
"""


def build_calibration_prompt(categories_present: list[str]) -> str:
    """
    Build calibration section for the Pass 2 system prompt.
    Includes universal anchors + category-specific anchors for competencies being scored.
    """
    parts = [UNIVERSAL_ANCHORS]

    # Add category-specific anchors for categories present in this assessment
    category_section_parts = []
    for cat in categories_present:
        if cat in CATEGORY_ANCHORS:
            category_section_parts.append(CATEGORY_ANCHORS[cat])
    if category_section_parts:
        parts.append("\n## CATEGORY-SPECIFIC ANCHORS\n" + "\n".join(category_section_parts))

    parts.append(FEW_SHOT_EXAMPLES)

    return "\n".join(parts)
