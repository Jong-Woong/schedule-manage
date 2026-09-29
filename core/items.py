"""PRD 3.2 파생 값 / 3.3 장소 비교 규칙 / 4장 F1 유효성 검사."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from core.models import ITEM_TYPES, Item, ItemStatus

STATUSES: tuple[ItemStatus, ...] = ("예정", "진행중", "완료", "지연")
NAME_MAX_LENGTH = 100
LOCATION_MAX_LENGTH = 50


def get_duration(item: Item) -> int:
    """기간(일) = 종료일 - 시작일 + 1 (달력일, 양 끝 포함)."""
    return (item.end_date - item.start_date).days + 1


def get_status(item: Item, today: date) -> ItemStatus:
    """상태 자동 계산.

    - 완료: 진행률 100
    - 지연: today > 종료일 이고 진행률 < 100
    - 진행중: 0 < 진행률 < 100, 또는 시작일 <= today <= 종료일
    - 예정: today < 시작일 이고 진행률 0
    """
    if item.progress >= 100:
        return "완료"
    if today > item.end_date:
        return "지연"
    if item.progress > 0 or item.start_date <= today:
        return "진행중"
    return "예정"


@dataclass
class ProgressSummary:
    overall: float
    """전체 진행률 = Σ(진행률 × 기간) / Σ(기간)"""
    fabrication: float
    installation: float


def _weighted(items: list[Item]) -> float:
    total = sum(get_duration(item) for item in items)
    if total == 0:
        return 0.0
    return sum(item.progress * get_duration(item) for item in items) / total


def get_overall_progress(items: list[Item]) -> ProgressSummary:
    """기간 가중 평균 진행률 (전체 / 제작 / 설치). 아이템이 없으면 0."""
    return ProgressSummary(
        overall=_weighted(items),
        fabrication=_weighted([item for item in items if item.type == "제작"]),
        installation=_weighted([item for item in items if item.type == "설치"]),
    )


def normalize_location(text: str) -> str:
    """장소 정규화: 모든 공백 제거 + 영문 소문자화. 결과가 같으면 같은 장소."""
    return re.sub(r"\s+", "", text or "").lower()


def location_labels(items: list[Item]) -> dict[str, str]:
    """정규화한 장소 → 화면에 보여줄 이름 (처음 등록된 표기). PRD 3.3: 공백·대소문자만 다르면 같은 장소."""
    labels: dict[str, str] = {}
    for item in items:
        labels.setdefault(normalize_location(item.location), item.location.strip())
    return labels


def validate_item_input(
    name: str,
    location: str,
    type_: str | None,
    start_date: date | None,
    end_date: date | None,
    progress: int | float | None = 0,
) -> list[str]:
    """입력값 유효성 검사. 오류 메시지 목록을 반환한다 (빈 목록이면 통과)."""
    errors: list[str] = []
    if not (name or "").strip():
        errors.append("공사 이름을 입력하세요.")
    elif len(name.strip()) > NAME_MAX_LENGTH:
        errors.append(f"공사 이름은 {NAME_MAX_LENGTH}자 이내로 입력하세요. (현재 {len(name.strip())}자)")
    if not (location or "").strip():
        errors.append("공사 장소를 입력하세요.")
    elif len(location.strip()) > LOCATION_MAX_LENGTH:
        errors.append(f"공사 장소는 {LOCATION_MAX_LENGTH}자 이내로 입력하세요. (현재 {len(location.strip())}자)")
    if type_ not in ITEM_TYPES:
        errors.append("구분은 '제작' 또는 '설치'여야 합니다.")
    if start_date is None:
        errors.append("시작일을 입력하세요.")
    if end_date is None:
        errors.append("종료일을 입력하세요.")
    if start_date and end_date and end_date < start_date:
        errors.append("종료일은 시작일보다 빠를 수 없습니다.")
    if progress is None or not 0 <= progress <= 100:
        errors.append("진행률은 0~100 사이여야 합니다.")
    return errors
