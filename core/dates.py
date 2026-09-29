"""날짜 유틸. Streamlit에 의존하지 않는다."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone


def today() -> date:
    """오늘 날짜. 환경 변수 APP_TODAY('YYYY-MM-DD')가 있으면 그 값을 사용한다 (테스트용)."""
    fixed = os.environ.get("APP_TODAY")
    if fixed:
        return date.fromisoformat(fixed)
    return date.today()


def now_iso() -> str:
    """현재 일시 (UTC, ISO 8601)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def from_iso(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
