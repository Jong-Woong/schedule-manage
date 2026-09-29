"""공정표 업로드 화면 (PRD 4장 F6·F7, 5장).

흐름: ① 파일 선택 → ② 열 매핑 → ③ 미리보기(오류 행 수정·장소 일괄 지정) → ④ 재분배 결과 확인 후 등록
업로드 진행 상태는 st.session_state에 보관해 화면이 다시 그려져도(rerun) 사라지지 않게 한다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.items import get_duration, normalize_location
from core.models import ITEM_TYPES, Item
from core.parser import (
    FIELD_LABELS,
    MappableField,
    ParsedRow,
    ScheduleParseError,
    detect_mapping,
    parse_date,
    read_table,
    recognize_rows,
    validate_values,
)
from core.reschedule import find_fabrication_warnings, reschedule_installations
from views.state import flash, get_items, modify, show_flash
from views.theme import PREVIEW_COLUMN_WIDTHS, md

S = "up_"  # 이 화면의 session_state 키 접두사
COLUMNS = {"name": "공사 이름", "location": "공사 장소", "type": "구분", "start_date": "시작일", "end_date": "종료일"}


def ss(name: str, default=None):
    return st.session_state.get(S + name, default)


def ss_set(name: str, value) -> None:
    st.session_state[S + name] = value


_KEEP = {S + "uploader_version", S + "file_version"}


def reset_upload(*, clear_file: bool) -> None:
    for key in [k for k in st.session_state if k.startswith(S) and k not in _KEEP]:
        del st.session_state[key]
    if clear_file:
        ss_set("uploader_version", ss("uploader_version", 0) + 1)


def to_rows(parsed: list[ParsedRow]) -> list[dict]:
    return [
        {"row": p.row_number, **p.values, "errors": p.errors, "excluded": False, "selected": False}
        for p in parsed
    ]


def revalidate(row: dict) -> None:
    row["errors"] = validate_values(row)


def bump_editor() -> None:
    ss_set("editor_version", ss("editor_version", 0) + 1)


def apply_editor_changes(editor_key: str) -> None:
    """data_editor에서 고친 값을 행 데이터에 반영하고 오류를 다시 검사한다."""
    rows: list[dict] = ss("rows")
    by_label = {label: field for field, label in COLUMNS.items()}
    for index, changes in st.session_state[editor_key]["edited_rows"].items():
        row = rows[int(index)]
        for label, value in changes.items():
            if label == "제외":
                row["excluded"] = bool(value)
            elif label == "선택":
                row["selected"] = bool(value)
            elif (field := by_label.get(label)) in ("start_date", "end_date"):
                try:
                    row[field] = parse_date(value)
                except ValueError:
                    row[field] = None
            elif field:
                row[field] = (value or "").strip() if field != "type" else value
        revalidate(row)
    bump_editor()


def valid_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r["excluded"] and not r["errors"]]


def period(item: Item) -> str:
    return f"{item.start_date} ~ {item.end_date}"


STEPS = ("파일 선택", "열 매핑", "미리보기", "등록")


def show_steps(current: int) -> None:
    """상단 단계 표시. current: 지금 진행 중인 단계(1~4)."""
    with stepper.container():
        cols = st.columns(len(STEPS))
        for number, (col, label) in enumerate(zip(cols, STEPS), start=1):
            if number < current:
                col.markdown(f"✅ :gray[{number}. {label}]")
            elif number == current:
                col.markdown(f"🔵 **{number}. {label}**")
            else:
                col.markdown(f"⚪ :gray[{number}. {label}]")


# ================================================================= 화면
st.title("📤 공정표 업로드")
show_flash()
stepper = st.empty()

# ---------------------------------------------------------------- ① 파일 선택
with st.container(key="upload_file"):
    uploaded = st.file_uploader(
        "공정표 파일 (.xlsx / .xls / .csv)",
        type=["xlsx", "xls", "csv"],
        key=f"upload_file_{ss('uploader_version', 0)}",
        help="파일을 끌어다 놓거나 눌러서 선택하세요. 엑셀 파일은 첫 번째 시트만 읽습니다.",
    )
if uploaded is None:
    reset_upload(clear_file=False)
    show_steps(1)
    st.caption(
        "공정표에는 **공사 이름 · 공사 장소 · 구분(제작/설치) · 시작일 · 종료일** 열이 있어야 합니다. "
        "열 이름이 조금 달라도(공사명, 위치, 착수일 등) 자동으로 찾아 연결합니다."
    )
    st.stop()

signature = (uploaded.name, uploaded.size, uploaded.file_id)
if ss("signature") != signature:
    reset_upload(clear_file=False)
    ss_set("signature", signature)
    # 파일마다 위젯 key를 바꿔, 이전 파일의 열 매핑 선택이 남지 않게 한다
    ss_set("file_version", ss("file_version", 0) + 1)
    try:
        table = read_table(uploaded.getvalue(), uploaded.name)
    except ScheduleParseError as exc:
        ss_set("error", str(exc))
    else:
        mapping = detect_mapping(table.headers)
        ss_set("table", table)
        ss_set("mapping", mapping)
        ss_set("rows", to_rows(recognize_rows(table, mapping)))

if error := ss("error"):
    show_steps(1)
    st.error(error, icon="🚫")
    st.stop()

table = ss("table")
rows: list[dict] = ss("rows")

# ---------------------------------------------------------------- ② 열 매핑
st.subheader("2. 열 매핑")
st.caption(f"{table.header_row_number}행을 헤더로 인식했습니다. 잘못 연결된 열이 있으면 바꿔 주세요.")
mapping: dict[MappableField, int] = dict(ss("mapping"))
column_options = [None, *range(len(table.headers))]
cols = st.columns(len(FIELD_LABELS))
new_mapping: dict[MappableField, int] = {}
for col, (field, label) in zip(cols, FIELD_LABELS.items()):
    choice = col.selectbox(
        label,
        column_options,
        index=column_options.index(mapping.get(field)),
        format_func=lambda i: "(없음)" if i is None else table.headers[i],
        key=f"{S}map_{field}_{ss('file_version')}",
    )
    if choice is not None:
        new_mapping[field] = choice
if new_mapping != mapping:
    ss_set("mapping", new_mapping)
    rows = to_rows(recognize_rows(table, new_mapping))
    ss_set("rows", rows)
    bump_editor()
    st.info("열 매핑이 바뀌어 파일을 다시 인식했습니다. (미리보기에서 고친 내용은 초기화됩니다)")
mapping = new_mapping

if not rows:
    show_steps(2)
    st.warning("헤더 아래에 데이터 행이 없습니다.")
    st.stop()

# ---------------------------------------------------------------- ③ 미리보기
st.subheader("3. 미리보기")

if "location" not in mapping:
    st.warning("공정표에 **공사 장소** 열이 없습니다. 모든 아이템에 적용할 공통 장소를 입력하거나, 미리보기에서 행별로 입력하세요.", icon="📍")
    cols = st.columns([3, 1], vertical_alignment="bottom")
    common = cols[0].text_input("공통 장소", key=f"{S}common_location_{ss('file_version')}", placeholder="예: A동 3층")
    if cols[1].button("모든 행에 적용", key="apply_common_location", disabled=not common.strip(), width="stretch"):
        for row in rows:
            row["location"] = common.strip()
            revalidate(row)
        bump_editor()
        st.rerun()

error_count = sum(1 for r in rows if r["errors"] and not r["excluded"])
excluded_count = sum(1 for r in rows if r["excluded"])
ready = valid_rows(rows)
cols = st.columns(4)
cols[0].metric("📄 인식된 행", f"{len(rows)}건", border=True)
cols[1].metric("✅ 등록 가능", f"{len(ready)}건", border=True)
cols[2].metric("❌ 오류", f"{error_count}건", border=True)
cols[3].metric("⏭️ 제외", f"{excluded_count}건", border=True)

editor_key = f"{S}editor_{ss('file_version')}_{ss('editor_version', 0)}"
preview = pd.DataFrame(
    [
        {
            "상태": "⏭️ 제외" if r["excluded"] else ("❌ 오류" if r["errors"] else "✅ 정상"),
            "제외": r["excluded"],
            "선택": r["selected"],
            "행": r["row"],
            "공사 이름": r["name"],
            "공사 장소": r["location"],
            "구분": r["type"],
            "시작일": r["start_date"],
            "종료일": r["end_date"],
            "오류": " / ".join(r["errors"]) if r["errors"] else "",
        }
        for r in rows
    ]
)
with st.container(key="preview_table"):
    st.data_editor(
        preview,
        hide_index=True,
        key=editor_key,
        on_change=apply_editor_changes,
        args=(editor_key,),
        num_rows="fixed",
        disabled=["상태", "행", "오류"],
        # 좁은 화면에서도 오류 사유가 먼저 보이도록 상태 바로 뒤에 둔다
        column_order=list(PREVIEW_COLUMN_WIDTHS),
        column_config={
            "상태": st.column_config.TextColumn(width=PREVIEW_COLUMN_WIDTHS["상태"], pinned=True),
            "오류": st.column_config.TextColumn("오류 사유", width=PREVIEW_COLUMN_WIDTHS["오류"]),
            "제외": st.column_config.CheckboxColumn(width=PREVIEW_COLUMN_WIDTHS["제외"], help="체크하면 등록하지 않습니다."),
            "선택": st.column_config.CheckboxColumn(width=PREVIEW_COLUMN_WIDTHS["선택"], help="장소 일괄 지정 대상"),
            "행": st.column_config.NumberColumn(width=PREVIEW_COLUMN_WIDTHS["행"]),
            "공사 이름": st.column_config.TextColumn(width=PREVIEW_COLUMN_WIDTHS["공사 이름"]),
            "공사 장소": st.column_config.TextColumn(width=PREVIEW_COLUMN_WIDTHS["공사 장소"]),
            "구분": st.column_config.SelectboxColumn(options=list(ITEM_TYPES), width=PREVIEW_COLUMN_WIDTHS["구분"]),
            "시작일": st.column_config.DateColumn(format="YYYY-MM-DD", width=PREVIEW_COLUMN_WIDTHS["시작일"]),
            "종료일": st.column_config.DateColumn(format="YYYY-MM-DD", width=PREVIEW_COLUMN_WIDTHS["종료일"]),
        },
    )
st.caption("셀을 더블클릭해 값을 고칠 수 있습니다. 고치면 오류를 다시 검사합니다.")

selected_rows = [r for r in rows if r["selected"]]
cols = st.columns([3, 1], vertical_alignment="bottom")
bulk_location = cols[0].text_input(
    f"선택한 행({len(selected_rows)}건)에 장소 일괄 지정", key=f"{S}bulk_location_{ss('file_version')}", placeholder="예: B동 1층"
)
if cols[1].button("선택 행에 적용", key="apply_bulk_location", disabled=not (selected_rows and bulk_location.strip()), width="stretch"):
    for row in selected_rows:
        row["location"] = bulk_location.strip()
        row["selected"] = False
        revalidate(row)
    bump_editor()
    st.rerun()

# ---------------------------------------------------------------- ④ 재분배 결과 확인 후 등록
if not ready:
    show_steps(3)
    st.warning("등록할 수 있는 행이 없습니다. 오류를 고치거나 제외 표시를 해제하세요.")
    st.stop()
show_steps(4)
st.subheader("4. 재분배 결과 확인 후 등록")

existing = get_items()
new_items = [
    Item(
        name=r["name"],
        location=r["location"],
        type=r["type"],
        start_date=r["start_date"],
        end_date=r["end_date"],
        source="upload",
    )
    for r in ready  # 공정표 행 순서 유지 → 재분배 우선순위 3순위
]
combined = [*existing, *new_items]
install_locations = {i.location for i in new_items if i.type == "설치"}
result = reschedule_installations(combined, locations=install_locations)
before = {i.id: i for i in combined}
new_ids = {i.id for i in new_items}

if result.changed_ids:
    st.warning(f"같은 장소에서 설치 일정이 겹쳐 **{len(result.changed_ids)}건**의 일정이 재분배됩니다. (설치 기간이 짧은 공사 우선)", icon="🔁")
    changed = [i for i in result.items if i.id in result.changed_ids]
    for loc in result.summary:
        with st.expander(
            f"📍 {md(loc.location)} — {loc.changed_count}건 변경 · 설치 완료일 {loc.last_end_before} → {loc.last_end_after}",
            expanded=True,
        ):
            st.dataframe(
                [
                    {
                        "공사 이름": i.name,
                        "구분": "신규" if i.id in new_ids else "기존 등록",
                        "기간(일)": get_duration(i),
                        "변경 전": period(before[i.id]),
                        "변경 후": period(i),
                    }
                    for i in changed
                    if normalize_location(i.location) == normalize_location(loc.location)
                ],
                hide_index=True,
                width="stretch",
            )
else:
    st.success("같은 장소에서 겹치는 설치 일정이 없어 재분배가 필요 없습니다.", icon="👍")

for warning in find_fabrication_warnings(result.items):
    st.warning(
        f"'{md(warning.name)}'({md(warning.location)})의 제작 종료일({warning.fabrication_end})이 "
        f"설치 시작일({warning.installation_start})보다 늦습니다.",
        icon="⚠️",
    )

skipped = len(rows) - len(ready)
label = f"{len(ready)}건 등록" + (f" (오류·제외 {skipped}건 제외)" if skipped else "")
if st.button(label, type="primary", icon=":material/playlist_add_check:", key="register_button"):
    info = {"changed": 0}

    def register(latest: list[Item]) -> list[Item]:
        # 미리보기 이후 다른 창에서 목록이 바뀌었을 수 있으므로, 저장 직전의 최신 목록으로 다시 재분배한다 (B1)
        final = reschedule_installations([*latest, *new_items], locations=install_locations)
        info["changed"] = len(final.changed_ids)
        return final.items

    modify(register)
    reset_upload(clear_file=True)
    flash(f"공정표에서 {len(ready)}건을 등록했습니다." + (f" 재분배 {info['changed']}건." if info["changed"] else ""))
    st.rerun()
