"""
Email notifications via Resend API.
If RESEND_API_KEY is not set, emails are silently skipped (no crash).
"""
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


async def _send(to: str, subject: str, html: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.debug("RESEND_API_KEY not set — skipping email to %s", to)
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.FROM_EMAIL,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            if resp.status_code >= 400:
                logger.warning("Resend error %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("Failed to send email to %s: %s", to, exc)


# ── Templates ─────────────────────────────────────────────────────────────────

def _base(content: str) -> str:
    return f"""
    <div style="font-family:Inter,sans-serif;background:#0f172a;color:#e2e8f0;padding:40px 0;min-height:100vh;">
      <div style="max-width:560px;margin:0 auto;background:#1e293b;border:1px solid #334155;border-radius:16px;padding:40px;">
        <div style="margin-bottom:32px;">
          <span style="color:#60a5fa;font-weight:700;font-size:20px;">AI</span>
          <span style="color:#f1f5f9;font-weight:700;font-size:20px;">Recruit</span>
        </div>
        {content}
        <div style="margin-top:40px;padding-top:24px;border-top:1px solid #334155;color:#64748b;font-size:13px;">
          AIRecruit · AI-powered recruiting platform
        </div>
      </div>
    </div>
    """


async def send_report_ready(
    candidate_email: str,
    candidate_name: str,
    role: str,
    overall_score: float,
    report_id: str,
    app_url: str,
) -> None:
    """Notify candidate that their assessment report is ready."""
    report_url = f"{app_url}/candidate/reports/{report_id}"
    score_color = "#4ade80" if overall_score >= 7 else "#facc15" if overall_score >= 5 else "#f87171"
    content = f"""
        <h1 style="color:#f1f5f9;font-size:24px;font-weight:700;margin:0 0 8px;">Your report is ready</h1>
        <p style="color:#94a3b8;margin:0 0 24px;">Hi {candidate_name}, your AI interview for <strong style="color:#e2e8f0;">{role}</strong> has been assessed.</p>

        <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:24px;margin-bottom:24px;text-align:center;">
          <div style="color:#94a3b8;font-size:13px;margin-bottom:8px;">Overall Score</div>
          <div style="font-size:48px;font-weight:700;color:{score_color};">{overall_score:.1f}<span style="font-size:20px;color:#64748b;">/10</span></div>
        </div>

        <a href="{report_url}" style="display:block;background:#2563eb;color:#fff;text-align:center;padding:14px;border-radius:10px;text-decoration:none;font-weight:600;font-size:15px;">
          View Full Report →
        </a>
    """
    await _send(
        to=candidate_email,
        subject=f"Your AIRecruit assessment report is ready — {overall_score:.1f}/10",
        html=_base(content),
    )


async def send_new_candidate_to_company(
    company_email: str,
    company_name: str,
    candidate_name: str,
    candidate_email: str,
    role: str,
    overall_score: float,
    hiring_recommendation: str,
    candidate_id: str,
    app_url: str,
) -> None:
    """Notify company admin that a new candidate completed an interview."""
    profile_url = f"{app_url}/company/candidates/{candidate_id}"
    rec_label = {
        "strong_yes": "Strong Yes ✅",
        "yes": "Yes ✓",
        "maybe": "Maybe",
        "no": "No ✗",
    }.get(hiring_recommendation, hiring_recommendation)
    rec_color = {
        "strong_yes": "#4ade80",
        "yes": "#60a5fa",
        "maybe": "#facc15",
        "no": "#f87171",
    }.get(hiring_recommendation, "#94a3b8")

    content = f"""
        <h1 style="color:#f1f5f9;font-size:24px;font-weight:700;margin:0 0 8px;">New verified candidate</h1>
        <p style="color:#94a3b8;margin:0 0 24px;">Hi {company_name}, a new candidate just completed their AI interview.</p>

        <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:24px;margin-bottom:24px;">
          <div style="margin-bottom:12px;">
            <div style="color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.05em;">Candidate</div>
            <div style="color:#f1f5f9;font-weight:600;">{candidate_name}</div>
            <div style="color:#64748b;font-size:13px;">{candidate_email}</div>
          </div>
          <div style="display:flex;gap:24px;">
            <div>
              <div style="color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.05em;">Role</div>
              <div style="color:#e2e8f0;">{role}</div>
            </div>
            <div>
              <div style="color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.05em;">Score</div>
              <div style="color:#e2e8f0;font-weight:700;">{overall_score:.1f}/10</div>
            </div>
            <div>
              <div style="color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.05em;">Recommendation</div>
              <div style="color:{rec_color};font-weight:600;">{rec_label}</div>
            </div>
          </div>
        </div>

        <a href="{profile_url}" style="display:block;background:#2563eb;color:#fff;text-align:center;padding:14px;border-radius:10px;text-decoration:none;font-weight:600;font-size:15px;">
          View Candidate Profile →
        </a>
    """
    await _send(
        to=company_email,
        subject=f"New candidate: {candidate_name} — {role} ({overall_score:.1f}/10)",
        html=_base(content),
    )
