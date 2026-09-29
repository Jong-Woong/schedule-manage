"""PRD 4장 F7 같은 장소의 설치 일정 중복 시 자동 재분배."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from core.dates import now_iso
from core.items import get_duration, normalize_location
from core.models import Item


@dataclass
class LocationSummary:
    location: str
    changed_count: int
    last_end_before: date
    """재분배 전 장소별 설치 완료일"""
    last_end_after: date
    """재분배 후 장소별 설치 완료일"""


@dataclass
class RescheduleResult:
    items: list[Item]
    """재분배가 반영된 새 목록 (입력과 같은 순서, 입력 목록은 변경하지 않음)"""
    changed_ids: list[str] = field(default_factory=list)
    summary: list[LocationSummary] = field(default_factory=list)


def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """PRD 7.2: 하루라도 겹치면 True."""
    return a_start <= b_end and b_start <= a_end


def is_fixed(item: Item) -> bool:
    """PRD 7.1: 진행률 > 0 인 아이템은 재분배 시 고정한다."""
    return item.progress > 0


def find_conflicts(candidate: Item, items: Iterable[Item]) -> list[Item]:
    """candidate(설치)와 같은 장소에서 설치 일정이 겹치는 다른 아이템 목록."""
    if candidate.type != "설치":
        return []
    key = normalize_location(candidate.location)
    return [
        other
        for other in items
        if other.id != candidate.id
        and other.type == "설치"
        and normalize_location(other.location) == key
        and overlaps(candidate.start_date, candidate.end_date, other.start_date, other.end_date)
    ]


def base_start(item: Item) -> date:
    """재분배 기준 시작일. 이미 재분배된 공사는 현재 시작일이 아니라 원래 시작일이 기준이다 (PRD 7.4 a).

    그래서 밀어낸 공사가 삭제되는 등 자리가 비면 원래 시작일로 돌아올 수 있다.
    """
    if item.rescheduled and item.original_start_date:
        return item.original_start_date
    return item.start_date


def reschedule_installations(
    items: list[Item],
    locations: Iterable[str] | None = None,
    *,
    only_rescheduled: bool = False,
) -> RescheduleResult:
    """같은 장소의 설치 아이템끼리 일정이 겹치면 뒤로 밀어 재분배한다 (PRD 7.4).

    - 우선순위: 기간 짧은 순 → (원래) 시작일 빠른 순 → 입력 목록 순서(= 공정표 행 순서)
    - 진행률 > 0 인 아이템은 고정(이동 금지)
    - 기간 유지, 원래 시작일보다 앞당기지 않음
    - 원래 시작일로 돌아온 공사는 재분배 표시를 지운다
    - locations를 주면 해당 장소(정규화 기준)만 재분배한다. 없으면 모든 장소.
    - only_rescheduled=True 이면 이미 재분배된 공사만 움직이고 나머지는 제자리에 둔다
      (삭제 후 복원용 — 사용자가 일부러 겹쳐 둔 다른 공사는 건드리지 않는다).
    """
    targets = {normalize_location(loc) for loc in locations} if locations is not None else None

    groups: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        if item.type != "설치":
            continue
        key = normalize_location(item.location)
        if targets is not None and key not in targets:
            continue
        groups.setdefault(key, []).append(index)

    def movable(item: Item) -> bool:
        return not is_fixed(item) and (item.rescheduled or not only_rescheduled)

    new_items = list(items)
    changed_ids: list[str] = []
    summary: list[LocationSummary] = []
    now = now_iso()

    for indices in groups.values():
        placed: list[tuple[date, date]] = [
            (items[i].start_date, items[i].end_date) for i in indices if not movable(items[i])
        ]
        ordered = sorted(
            (i for i in indices if movable(items[i])),
            key=lambda i: (get_duration(items[i]), base_start(items[i]), i),
        )
        group_changed = 0

        for i in ordered:
            item = items[i]
            length = timedelta(days=get_duration(item) - 1)
            start = base_start(item)
            while True:
                hits = [(s, e) for s, e in placed if overlaps(start, start + length, s, e)]
                if not hits:
                    break
                # PRD 7.4 c: 겹친 구간의 종료일 + 1일로 옮기고 다시 검사
                start = min(e for _, e in hits) + timedelta(days=1)
            end = start + length
            placed.append((start, end))

            if start == item.start_date:
                continue
            if item.rescheduled and start == item.original_start_date:
                # 원래 자리로 복귀
                new_items[i] = dataclasses.replace(
                    item, start_date=start, end_date=end,
                    original_start_date=None, original_end_date=None, rescheduled=False, updated_at=now,
                )
            else:
                new_items[i] = dataclasses.replace(
                    item,
                    start_date=start,
                    end_date=end,
                    # 이미 재분배된 적이 있으면 최초 원래 일정을 유지한다
                    original_start_date=item.original_start_date or item.start_date,
                    original_end_date=item.original_end_date or item.end_date,
                    rescheduled=True,
                    updated_at=now,
                )
            changed_ids.append(item.id)
            group_changed += 1

        if group_changed:
            summary.append(
                LocationSummary(
                    location=items[indices[0]].location.strip(),
                    changed_count=group_changed,
                    last_end_before=max(items[i].end_date for i in indices),
                    last_end_after=max(new_items[i].end_date for i in indices),
                )
            )

    return RescheduleResult(items=new_items, changed_ids=changed_ids, summary=summary)


def remove_and_restore(items: list[Item], item_ids: Iterable[str]) -> RescheduleResult:
    """아이템을 삭제하고, 삭제된 설치 공사가 있던 장소에서 밀려나 있던 공사를 원래 시작일 쪽으로 되돌린다.

    반환 items 는 삭제가 반영된 목록, changed_ids 는 되돌아온 공사.
    """
    targets = set(item_ids)
    removed = [i for i in items if i.id in targets]
    remaining = [i for i in items if i.id not in targets]
    locations = {i.location for i in removed if i.type == "설치"}
    if not locations:
        return RescheduleResult(items=remaining)
    return reschedule_installations(remaining, locations=locations, only_rescheduled=True)


def revert_to_original(item: Item) -> Item:
    """재분배된 아이템을 원래 일정으로 되돌린다. 재분배된 적이 없으면 그대로 반환."""
    if not item.rescheduled or not item.original_start_date or not item.original_end_date:
        return item
    return dataclasses.replace(
        item,
        start_date=item.original_start_date,
        end_date=item.original_end_date,
        original_start_date=None,
        original_end_date=None,
        rescheduled=False,
        updated_at=now_iso(),
    )


@dataclass
class FabricationWarning:
    name: str
    location: str
    fabrication_end: date
    installation_start: date


def find_fabrication_warnings(items: list[Item]) -> list[FabricationWarning]:
    """PRD 7.6: 같은 공사(이름·장소)의 제작 종료일이 설치 시작일보다 늦은 경우."""
    fabrication: dict[tuple[str, str], list[Item]] = {}
    for item in items:
        if item.type == "제작":
            fabrication.setdefault((item.name.strip(), normalize_location(item.location)), []).append(item)

    warnings: list[FabricationWarning] = []
    for item in items:
        if item.type != "설치":
            continue
        for fab in fabrication.get((item.name.strip(), normalize_location(item.location)), []):
            if fab.end_date > item.start_date:
                warnings.append(
                    FabricationWarning(
                        name=item.name,
                        location=item.location,
                        fabrication_end=fab.end_date,
                        installation_start=item.start_date,
                    )
                )
    return warnings
