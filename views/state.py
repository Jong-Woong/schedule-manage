"""화면 상태 관리.

- 목록은 st.session_state 에 캐시하되, 저장 파일이 바뀌었으면(다른 탭에서 저장) 화면을 그릴 때 다시 읽는다.
- 모든 변경은 core.storage.modify_items 로 "저장 직전의 최신 파일"을 기준으로 적용한다.
  → 브라우저 탭 여러 개가 서로의 추가·삭제를 덮어쓰지 않는다 (B1).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import streamlit as st

from core.dates import now_iso
from core.models import Item
from core.storage import data_path, file_signature, load_items, modify_items

_ITEMS_KEY = "pm_items"
_SIGNATURE_KEY = "pm_signature"
_WARNING_KEY = "pm_load_warning"
_FLASH_KEY = "pm_flash"
_TABLE_VERSION_KEY = "pm_table_version"


def get_items() -> list[Item]:
    """현재 목록. 세션 첫 접근이거나 저장 파일이 다른 곳에서 바뀌었으면 파일에서 다시 읽는다."""
    signature = file_signature(data_path())
    first = _ITEMS_KEY not in st.session_state
    if first or st.session_state.get(_SIGNATURE_KEY) != signature:
        result = load_items()
        st.session_state[_ITEMS_KEY] = result.items
        st.session_state[_SIGNATURE_KEY] = file_signature(data_path())
        if result.warning:
            st.session_state[_WARNING_KEY] = result.warning
        if not first:
            # 다른 탭의 변경으로 목록이 바뀌었으니 표의 행 선택을 초기화한다
            _bump_table_version()
            st.session_state.setdefault(_FLASH_KEY, ("다른 창에서 변경된 내용을 불러왔습니다.", "🔄"))
    return st.session_state[_ITEMS_KEY]


def pop_load_warning() -> str | None:
    """저장 파일 손상 경고를 한 번만 꺼낸다."""
    return st.session_state.pop(_WARNING_KEY, None)


def modify(mutator: Callable[[list[Item]], list[Item]]) -> list[Item]:
    """최신 파일 기준으로 목록을 바꾸고 저장한다. 목록 표의 행 선택은 초기화한다."""
    updated = modify_items(mutator)
    st.session_state[_ITEMS_KEY] = updated
    st.session_state[_SIGNATURE_KEY] = file_signature(data_path())
    _bump_table_version()
    return updated


def _bump_table_version() -> None:
    st.session_state[_TABLE_VERSION_KEY] = table_version() + 1


def table_version() -> int:
    return st.session_state.get(_TABLE_VERSION_KEY, 0)


def add_item(item: Item) -> None:
    modify(lambda items: [*items, item])


def update_item(item_id: str, **changes) -> None:
    now = now_iso()
    modify(
        lambda items: [
            dataclasses.replace(item, **changes, updated_at=now) if item.id == item_id else item for item in items
        ]
    )


def remove_many(item_ids: list[str]) -> None:
    targets = set(item_ids)
    modify(lambda items: [item for item in items if item.id not in targets])


def flash(message: str, icon: str = "✅") -> None:
    """다음 화면 갱신 때 한 번 보여줄 완료 메시지."""
    st.session_state[_FLASH_KEY] = (message, icon)


def show_flash() -> None:
    if entry := st.session_state.pop(_FLASH_KEY, None):
        message, icon = entry
        st.toast(message, icon=icon)
        st.success(message, icon=icon)
