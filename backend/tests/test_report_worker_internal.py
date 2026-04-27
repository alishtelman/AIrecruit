import pytest
from fastapi import HTTPException

from app.api.v1.internal import _verify_worker_token
from app.core.config import settings


def test_verify_worker_token_accepts_configured_token():
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = "secret"
    try:
        _verify_worker_token("secret")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token


def test_verify_worker_token_rejects_invalid_token():
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = "secret"
    try:
        with pytest.raises(HTTPException) as exc_info:
            _verify_worker_token("wrong")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token

    assert exc_info.value.status_code == 403


def test_verify_worker_token_requires_configured_token():
    original_token = settings.INTERNAL_WORKER_TOKEN
    settings.INTERNAL_WORKER_TOKEN = ""
    try:
        with pytest.raises(HTTPException) as exc_info:
            _verify_worker_token("secret")
    finally:
        settings.INTERNAL_WORKER_TOKEN = original_token

    assert exc_info.value.status_code == 503

