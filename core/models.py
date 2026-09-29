"""PRD 3.1 공정 아이템 데이터 모델."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from core.dates import from_iso, now_iso, to_iso

ItemType = Literal["제작", "설치"]
ItemSource = Literal["manual", "upload"]
ItemStatus = Literal["예정", "진행중", "완료", "지연"]

ITEM_TYPES: tuple[ItemType, ...] = ("제작", "설치")


@dataclass
class Item:
    name: str
    """공사 이름"""
    location: str
    """공사 장소 — 설치 일정 중복 판단 기준"""
    type: ItemType
    """구분: 제작 | 설치"""
    start_date: date
    end_date: date
    progress: int = 0
    """진행률 0~100"""
    original_start_date: date | None = None
    """재분배 전 원래 시작일"""
    original_end_date: date | None = None
    """재분배 전 원래 종료일"""
    rescheduled: bool = False
    source: ItemSource = "manual"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """JSON 저장용 dict. 날짜는 'YYYY-MM-DD' 문자열."""
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "type": self.type,
            "start_date": to_iso(self.start_date),
            "end_date": to_iso(self.end_date),
            "progress": self.progress,
            "original_start_date": to_iso(self.original_start_date),
            "original_end_date": to_iso(self.original_end_date),
            "rescheduled": self.rescheduled,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Item:
        """to_dict()의 역변환. 필수 키가 없거나 형식이 틀리면 KeyError/ValueError."""
        start = from_iso(data["start_date"])
        end = from_iso(data["end_date"])
        if start is None or end is None:
            raise ValueError("시작일/종료일이 비어 있습니다.")
        return cls(
            id=data["id"],
            name=data["name"],
            location=data["location"],
            type=data["type"],
            start_date=start,
            end_date=end,
            progress=int(data.get("progress", 0)),
            original_start_date=from_iso(data.get("original_start_date")),
            original_end_date=from_iso(data.get("original_end_date")),
            rescheduled=bool(data.get("rescheduled", False)),
            source=data.get("source", "manual"),
            created_at=data.get("created_at") or now_iso(),
            updated_at=data.get("updated_at") or now_iso(),
        )
