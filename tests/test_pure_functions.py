"""Unit tests for pure helpers across the app.

Covers utility functions that are safe to test in isolation without
mocking LangGraph, FastAPI request context, or the LLM provider.
Kept intentionally small — this exists so `pytest` on a fresh clone
reports actual test signal instead of `no tests collected` (audit
finding P1, decisions.md § 8.11).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from groq import RateLimitError

from matchday_agent.app import (
    _format_error_frame,
    _validate_provider_credentials,
    _validate_session_id,
)
from matchday_agent.streaming import extract_chunk_text, format_tool_input


@dataclass
class _MockChunk:
    content: Any


class TestExtractChunkText:
    def test_string_content(self) -> None:
        assert extract_chunk_text(_MockChunk(content="hello")) == "hello"

    def test_list_of_dicts_with_text(self) -> None:
        chunk = _MockChunk(content=[{"text": "hello "}, {"text": "world"}])
        assert extract_chunk_text(chunk) == "hello world"

    def test_list_with_non_text_parts_skipped(self) -> None:
        chunk = _MockChunk(content=[{"reasoning": "thinking"}, {"text": "answer"}])
        assert extract_chunk_text(chunk) == "answer"

    def test_none_content(self) -> None:
        assert extract_chunk_text(_MockChunk(content=None)) == ""

    def test_no_content_attribute(self) -> None:
        assert extract_chunk_text(object()) == ""


class TestFormatToolInput:
    def test_dict_input(self) -> None:
        assert format_tool_input({"a": 1, "b": "c"}) == "a=1, b='c'"

    def test_non_dict_input(self) -> None:
        assert format_tool_input("raw") == "raw"


class TestFormatErrorFrame:
    def test_generic_exception_falls_back_to_type_name_and_message(self) -> None:
        error = ValueError("bad input")
        assert _format_error_frame(error) == {
            "code": "ValueError",
            "message": "bad input",
        }

    def test_groq_rate_limit_error_returns_friendly_code(self) -> None:
        response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "http://example.test"),
        )
        error = RateLimitError(message="quota", response=response, body={})
        result = _format_error_frame(error)
        assert result["code"] == "RateLimit"
        assert "Daily token quota" in result["message"]


class TestValidateSessionId:
    def test_valid_uuid_returned_verbatim(self) -> None:
        sid = "550e8400-e29b-41d4-a716-446655440000"
        assert _validate_session_id(sid) == sid

    def test_missing_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validate_session_id(None)
        assert exc_info.value.status_code == 400
        assert "required" in str(exc_info.value.detail).lower()

    def test_invalid_uuid_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validate_session_id("not-a-uuid")
        assert exc_info.value.status_code == 400


class TestValidateProviderCredentials:
    def test_groq_with_key_present_no_raise(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "sk-test"}):
            _validate_provider_credentials("groq")

    def test_groq_missing_key_raises_with_fix_command(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(RuntimeError, match="GROQ_API_KEY"),
        ):
            _validate_provider_credentials("groq")

    def test_google_genai_with_key_present_no_raise(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "sk-test"}):
            _validate_provider_credentials("google_genai")

    def test_unknown_provider_skips_validation(self) -> None:
        _validate_provider_credentials("some_future_provider")
