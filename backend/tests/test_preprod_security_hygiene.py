from app.ai.practical_tasks import TASK_BANK, get_task_for_frontend
from app.api.v1.auth import _mask_email as mask_auth_email
from app.services.email_service import _mask_email as mask_notification_email


def test_auth_and_email_log_helpers_mask_pii_email():
    assert mask_auth_email("candidate@example.com") == "ca***@example.com"
    assert mask_notification_email("a@example.com") == "a***@example.com"
    assert "candidate@example.com" not in mask_auth_email("candidate@example.com")


def test_practical_task_frontend_payload_never_exposes_hidden_solution_fields():
    for role, tasks in TASK_BANK.items():
        for task in tasks:
            payload = get_task_for_frontend(task, "ru")
            assert "expected_solution" not in payload, role
            assert "evaluation_rubric" not in payload, role
            assert task.get("expected_solution") != payload.get("instruction")
