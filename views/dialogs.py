"""아이템 추가/수정 · 삭제 확인 대화상자 (PRD 4장 F1·F3·F4·F5, 5장)."""

from __future__ import annotations

import dataclasses

import streamlit as st

from core.items import NAME_MAX_LENGTH, location_labels, validate_item_input
from core.models import ITEM_TYPES, Item
from core.reschedule import find_conflicts, remove_and_restore, reschedule_installations
from views.state import flash, get_items, modify
from views.theme import md, type_label

_FORM_FIELDS = ("name", "location", "type", "start", "end", "progress")
_PENDING_KEY = "item_form_pending"
QUICK_PROGRESS = (0, 25, 50, 75, 100)


def _key(field: str) -> str:
    return f"item_form_{field}"


def _period(item: Item) -> str:
    return f"{item.start_date} ~ {item.end_date}"


def open_item_dialog(item: Item | None = None) -> None:
    """추가(item=None) 또는 수정 대화상자를 연다. 버튼을 누른 그 실행에서만 호출해야 한다."""
    values = {
        "name": item.name if item else "",
        "location": item.location if item else None,
        "type": item.type if item else "설치",
        "start": item.start_date if item else None,
        "end": item.end_date if item else None,
        "progress": item.progress if item else 0,
    }
    for field in _FORM_FIELDS:
        st.session_state[_key(field)] = values[field]
    st.session_state.pop(_PENDING_KEY, None)
    _item_dialog(item.id if item else None)


def _form_values(item: Item) -> tuple:
    return (item.name, item.location, item.type, item.start_date, item.end_date, item.progress)


def _set_progress(value: int) -> None:
    st.session_state[_key("progress")] = value


def _save(candidate: Item, *, is_new: bool, apply_reschedule: bool) -> None:
    info = {"missing": False, "changed": 0}

    def mutate(items: list[Item]) -> list[Item]:
        # 저장 직전의 최신 목록 기준 (다른 탭에서 바뀌었을 수 있음)
        if not is_new and all(i.id != candidate.id for i in items):
            info["missing"] = True
            return items
        new_items = [*items, candidate] if is_new else [candidate if i.id == candidate.id else i for i in items]
        if apply_reschedule:
            result = reschedule_installations(new_items, locations=[candidate.location])
            info["changed"] = len(result.changed_ids)
            return result.items
        return new_items

    modify(mutate)
    st.session_state.pop(_PENDING_KEY, None)
    if info["missing"]:
        flash("다른 창에서 이미 삭제된 아이템이라 저장하지 못했습니다.", icon="⚠️")
    else:
        message = f"'{md(candidate.name)}' {'추가' if is_new else '수정'} 완료"
        if apply_reschedule:
            message += f" · 재분배로 {info['changed']}건의 일정이 변경되었습니다"
        flash(message)
    st.rerun()


@st.dialog("공정 아이템", width="large", icon=":material/construction:")
def _item_dialog(item_id: str | None) -> None:
    items = get_items()
    # 추가/수정 여부는 연 방식으로 정한다 — 목록에서 못 찾는다고 '추가'로 바꾸면, 다른 창에서 삭제된 아이템이 되살아난다
    is_new = item_id is None
    original = None if is_new else next((i for i in items if i.id == item_id), None)
    if not is_new and original is None:
        st.warning("다른 창에서 이미 삭제된 아이템입니다. 수정할 수 없습니다.", icon="⚠️")
        if st.button("닫기", key="item_form_close_missing", width="stretch"):
            st.rerun()
        return
    st.subheader("새 아이템 추가" if is_new else f"'{md(original.name)}' 수정")

    # 공백·대소문자만 다른 장소는 한 번만 보여준다 (B2)
    locations = sorted(location_labels(items).values())
    current_location = st.session_state.get(_key("location"))
    if current_location and current_location not in locations:
        locations.append(current_location)

    col1, col2 = st.columns(2)
    # max_chars 를 쓰면 제한을 넘는 붙여넣기가 통째로 무시되므로, 길이는 저장할 때 검사한다 (B3)
    name = col1.text_input(
        "공사 이름", key=_key("name"), placeholder="예: 1층 창호 공사", help=f"최대 {NAME_MAX_LENGTH}자"
    )
    location = col2.selectbox(
        "공사 장소",
        locations,
        key=_key("location"),
        accept_new_options=True,
        index=None,
        placeholder="선택하거나 새 장소를 입력",
        help="같은 장소의 설치 일정이 겹치면 재분배 대상이 됩니다.",
    )
    type_ = st.radio(
        "구분",
        ITEM_TYPES,
        key=_key("type"),
        horizontal=True,
        format_func=type_label,
        help="설치 아이템만 같은 장소의 일정 겹침을 검사합니다.",
    )
    col1, col2 = st.columns(2)
    start = col1.date_input("시작일", key=_key("start"), format="YYYY-MM-DD")
    end = col2.date_input("종료일", key=_key("end"), format="YYYY-MM-DD")

    progress = st.slider(
        "진행률 (%)",
        0,
        100,
        step=1,
        key=_key("progress"),
        help="진행률이 0%보다 큰 설치 공사는 재분배할 때 일정이 고정됩니다.",
    )
    quick = st.columns(len(QUICK_PROGRESS))
    for col, value in zip(quick, QUICK_PROGRESS):
        col.button(f"{value}%", key=f"item_form_quick_{value}", on_click=_set_progress, args=(value,), width="stretch")

    errors = validate_item_input(name, location or "", type_, start, end, progress)
    candidate = None
    if not errors:
        dates_changed = original is not None and (original.start_date, original.end_date) != (start, end)
        base = original or Item(name="", location="", type="설치", start_date=start, end_date=end)
        candidate = dataclasses.replace(
            base,
            name=name.strip(),
            location=location.strip(),
            type=type_,
            start_date=start,
            end_date=end,
            progress=int(progress),
            # 일정을 직접 바꾸면 재분배 표시를 지운다
            **({"rescheduled": False, "original_start_date": None, "original_end_date": None} if dates_changed else {}),
        )

    # 겹침 경고 이후 입력값을 바꾸면 경고를 다시 확인해야 한다
    pending: Item | None = st.session_state.get(_PENDING_KEY)
    if pending is not None and (candidate is None or _form_values(pending) != _form_values(candidate)):
        st.session_state.pop(_PENDING_KEY)
        pending = None

    st.divider()
    if pending is None:
        col1, col2 = st.columns(2)
        if col1.button("저장", type="primary", icon=":material/save:", key="item_form_save", width="stretch"):
            if errors:
                for message in errors:
                    st.error(message)
            else:
                conflicts = find_conflicts(candidate, [i for i in items if i.id != candidate.id])
                if conflicts:
                    st.session_state[_PENDING_KEY] = candidate
                    st.rerun(scope="fragment")
                _save(candidate, is_new=is_new, apply_reschedule=False)
        if col2.button("취소", key="item_form_cancel", width="stretch"):
            st.rerun()
        return

    # ---- 같은 장소 설치 일정 겹침 경고 (PRD F1) ----
    others = [i for i in items if i.id != pending.id]
    conflicts = find_conflicts(pending, others)
    st.warning(
        f"'**{md(pending.location)}**'에서 설치 일정이 겹치는 공사가 **{len(conflicts)}건** 있습니다. "
        "재분배를 적용할지, 겹친 채로 저장할지 선택하세요.",
        icon="⚠️",
    )
    st.dataframe(
        [{"공사 이름": c.name, "공사 장소": c.location, "설치 일정": _period(c), "진행률(%)": c.progress} for c in conflicts],
        hide_index=True,
        width="stretch",
    )
    trial_items = [*others, pending]
    trial = reschedule_installations(trial_items, locations=[pending.location])
    before = {i.id: i for i in trial_items}
    if trial.changed_ids:
        st.caption("재분배를 적용하면 아래와 같이 변경됩니다. (설치 기간이 짧은 공사 우선)")
        st.dataframe(
            [
                {"공사 이름": i.name, "변경 전": _period(before[i.id]), "변경 후": _period(i)}
                for i in trial.items
                if i.id in trial.changed_ids
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("진행 중인 공사는 고정되어, 재분배를 적용해도 변경되는 일정이 없습니다.")

    col1, col2, col3 = st.columns(3)
    if col1.button("재분배 적용", type="primary", icon=":material/event_repeat:", key="item_form_apply_reschedule", width="stretch"):
        _save(pending, is_new=is_new, apply_reschedule=True)
    if col2.button("그대로 저장", key="item_form_save_anyway", width="stretch"):
        _save(pending, is_new=is_new, apply_reschedule=False)
    if col3.button("돌아가기", key="item_form_back", width="stretch"):
        st.session_state.pop(_PENDING_KEY, None)
        st.rerun(scope="fragment")


@st.dialog("삭제 확인", icon=":material/delete:")
def open_delete_dialog(item_ids: list[str]) -> None:
    targets = [i for i in get_items() if i.id in set(item_ids)]
    st.write(f"다음 **{len(targets)}건**을 삭제합니다. 삭제한 아이템은 되돌릴 수 없습니다.")
    st.dataframe(
        [{"공사 이름": i.name, "공사 장소": i.location, "구분": i.type, "일정": _period(i)} for i in targets],
        hide_index=True,
        width="stretch",
    )
    col1, col2 = st.columns(2)
    if col1.button("삭제", type="primary", icon=":material/delete:", key="delete_confirm", width="stretch"):
        info = {"restored": 0}

        def mutate(items: list[Item]) -> list[Item]:
            # 삭제한 공사 때문에 밀려나 있던 공사는 원래 시작일 쪽으로 되돌린다 (B4)
            result = remove_and_restore(items, [i.id for i in targets])
            info["restored"] = len(result.changed_ids)
            return result.items

        modify(mutate)
        message = f"{len(targets)}건 삭제 완료"
        if info["restored"]:
            message += f" · 밀려나 있던 {info['restored']}건의 일정을 원래 쪽으로 되돌렸습니다"
        flash(message, icon="🗑️")
        st.rerun()
    if col2.button("취소", key="delete_cancel", width="stretch"):
        st.rerun()
