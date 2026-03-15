"""Tests for company interview template CRUD and public listing."""
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_create_and_list_templates(client: AsyncClient, company_token: str):
    # Create template
    resp = await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": "Backend Deep Dive",
            "target_role": "backend_engineer",
            "questions": [
                "Describe your experience with microservices.",
                "How do you handle database migrations?",
            ],
            "description": "Two-question screen",
            "is_public": True,
        },
    )
    assert resp.status_code == 201
    tmpl = resp.json()
    assert tmpl["name"] == "Backend Deep Dive"
    assert len(tmpl["questions"]) == 2
    assert tmpl["is_public"] is True
    template_id = tmpl["template_id"]

    # List company templates
    resp = await client.get(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
    )
    assert resp.status_code == 200
    templates = resp.json()
    ids = [t["template_id"] for t in templates]
    assert template_id in ids


@pytest.mark.asyncio
async def test_public_templates_endpoint(client: AsyncClient, company_token: str):
    # Create a public template
    await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": "Public Screen",
            "target_role": "frontend_engineer",
            "questions": ["Question 1"],
            "is_public": True,
        },
    )
    # Create a private template
    await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": "Internal Only",
            "target_role": "frontend_engineer",
            "questions": ["Question 1"],
            "is_public": False,
        },
    )

    # Public endpoint should only return public templates
    resp = await client.get("/api/v1/interviews/templates/public")
    assert resp.status_code == 200
    public = resp.json()
    names = [t["name"] for t in public]
    assert "Public Screen" in names
    assert "Internal Only" not in names


@pytest.mark.asyncio
async def test_delete_template(client: AsyncClient, company_token: str):
    # Create
    resp = await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": "To Delete",
            "target_role": "qa_engineer",
            "questions": ["Q1"],
            "is_public": False,
        },
    )
    template_id = resp.json()["template_id"]

    # Delete
    resp = await client.delete(
        f"/api/v1/company/templates/{template_id}",
        headers=auth_headers(company_token),
    )
    assert resp.status_code == 204

    # Should be gone
    resp = await client.get(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
    )
    ids = [t["template_id"] for t in resp.json()]
    assert template_id not in ids


@pytest.mark.asyncio
async def test_delete_other_company_template(
    client: AsyncClient, company_token: str
):
    """A company admin cannot delete another company's template."""
    # Create template as company_token
    resp = await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": "Protected",
            "target_role": "backend_engineer",
            "questions": ["Q1"],
            "is_public": False,
        },
    )
    template_id = resp.json()["template_id"]

    # Register a second company
    email2 = f"other_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/company/register", json={
        "email": email2, "password": "testpass123", "company_name": "Other Corp",
    })
    resp2 = await client.post("/api/v1/auth/login", json={
        "email": email2, "password": "testpass123",
    })
    other_token = resp2.json()["access_token"]

    # Try to delete with the other company's token
    resp = await client.delete(
        f"/api/v1/company/templates/{template_id}",
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_candidate_cannot_create_template(
    client: AsyncClient, candidate_token: str
):
    resp = await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(candidate_token),
        json={
            "name": "Sneaky",
            "target_role": "backend_engineer",
            "questions": ["Q1"],
            "is_public": True,
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_interview_with_template(
    client: AsyncClient, candidate_token: str, company_token: str
):
    """Start an interview using a template — questions go through LLM."""
    # Create a template
    resp = await client.post(
        "/api/v1/company/templates",
        headers=auth_headers(company_token),
        json={
            "name": "Template Test",
            "target_role": "backend_engineer",
            "questions": ["Tell me about APIs.", "Tell me about databases."],
            "is_public": True,
        },
    )
    template_id = resp.json()["template_id"]

    # Upload resume as candidate
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    await client.post(
        "/api/v1/candidate/resume/upload",
        headers=auth_headers(candidate_token),
        files={"file": ("cv.pdf", pdf, "application/pdf")},
    )

    # Start interview with template
    resp = await client.post(
        "/api/v1/interviews/start",
        headers=auth_headers(candidate_token),
        json={"target_role": "backend_engineer", "template_id": template_id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["max_questions"] == 2  # matches template length
    assert data["current_question"]  # LLM generated, not empty
