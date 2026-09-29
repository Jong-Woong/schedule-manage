"""대시보드 (PRD 4장 F2·F4·F5·F7, 5장)."""

import pandas as pd
import streamlit as st

from core.dates import today
from core.export import export_xlsx
from core.items import STATUSES, get_duration, get_overall_progress, get_status, location_labels, normalize_location
from core.models import ITEM_TYPES, Item
from core.reschedule import revert_to_original
from views.dialogs import open_delete_dialog, open_item_dialog
from views.gantt import build_gantt
from views.state import flash, get_items, modify, pop_load_warning, show_flash, table_version
from views.theme import RESCHEDULED_LABEL, STATUS_HELP, STATUS_ICONS, status_label, type_label

SORT_OPTIONS = {
    "시작일": lambda i: (i.start_date, i.end_date, i.name),
    "공사 이름": lambda i: (i.name, i.start_date),
    "공사 장소": lambda i: (i.location, i.start_date),
    "진행률": lambda i: (i.progress, i.start_date),
}


def display_frame(items: list[Item]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "공사 이름": i.name,
                "공사 장소": i.location,
                "구분": type_label(i.type),
                "시작일": i.start_date,
                "종료일": i.end_date,
                "기간(일)": get_duration(i),
                "진행률": i.progress,
                "상태": status_label(get_status(i, now)),
                "재분배": RESCHEDULED_LABEL if i.rescheduled else "",
                "원래 일정": f"{i.original_start_date} ~ {i.original_end_date}" if i.rescheduled else "",
            }
            for i in items
        ]
    )


def upload_button(key: str) -> None:
    if st.button("공정표 업로드", icon=":material/upload_file:", key=key, width="stretch"):
        st.switch_page("views/upload.py")


items = get_items()
now = today()

st.title("🏗️ 공정 관리")
st.caption(f"오늘 {now:%Y-%m-%d} · 전체 {len(items)}건")
if warning := pop_load_warning():
    st.warning(warning, icon="⚠️")
show_flash()

# ---------------------------------------------------------------- 빈 상태
if not items:
    with st.container(border=True, key="empty_state"):
        st.subheader("아직 등록된 공정이 없습니다")
        st.write("엑셀·CSV 공정표를 올리면 한 번에 등록되고, 같은 장소의 설치 일정이 겹치면 자동으로 재분배됩니다.")
        cols = st.columns([1, 1, 2])
        with cols[0]:
            upload_button("go_upload_button")
        if cols[1].button("직접 추가", icon=":material/add:", key="add_item_button", width="stretch"):
            open_item_dialog()
    st.stop()

# ---------------------------------------------------------------- 진행률 요약 (F5)
summary = get_overall_progress(items)
cols = st.columns(3)
for col, label, value, helptext in (
    (cols[0], "전체 진행률", summary.overall, "기간 가중 평균 = Σ(진행률×기간) / Σ(기간)"),
    (cols[1], "🏭 제작 진행률", summary.fabrication, "제작 아이템만의 기간 가중 평균"),
    (cols[2], "🔧 설치 진행률", summary.installation, "설치 아이템만의 기간 가중 평균"),
):
    with col.container(border=True):
        st.metric(label, f"{value:.1f}%", help=helptext)
        st.progress(min(int(round(value)), 100))

status_counts = {status: 0 for status in STATUSES}
for item in items:
    status_counts[get_status(item, now)] += 1
cols = st.columns(len(STATUSES))
for col, status in zip(cols, STATUSES):
    col.metric(f"{STATUS_ICONS[status]} {status}", f"{status_counts[status]}건", help=STATUS_HELP[status], border=True)

# ---------------------------------------------------------------- 주요 버튼
cols = st.columns([1, 1, 1, 0.6])
if cols[0].button("아이템 추가", type="primary", icon=":material/add:", key="add_item_button", width="stretch"):
    open_item_dialog()
with cols[1]:
    upload_button("go_upload_button")
cols[2].download_button(
    "엑셀 내보내기",
    data=export_xlsx(items, now),
    file_name=f"공정목록_{now:%Y%m%d}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
    key="export_button",
    width="stretch",
)

# ---------------------------------------------------------------- 필터·정렬 (F2)
with st.container(border=True, key="filter_bar"):
    cols = st.columns([1, 1, 2, 1, 1], vertical_alignment="bottom")
    type_filter = cols[0].multiselect("구분", ITEM_TYPES, key="filter_type", placeholder="전체")
    status_filter = cols[1].multiselect("상태", STATUSES, key="filter_status", placeholder="전체")
    # 공백·대소문자만 다른 장소는 하나의 선택지로 묶는다 (B2)
    location_filter = cols[2].multiselect(
        "공사 장소", sorted(location_labels(items).values()), key="filter_location", placeholder="전체"
    )
    sort_by = cols[3].selectbox("정렬", list(SORT_OPTIONS), key="sort_by")
    descending = cols[4].toggle("내림차순", key="sort_desc")

location_keys = {normalize_location(loc) for loc in location_filter}
visible = [
    item
    for item in items
    if (not type_filter or item.type in type_filter)
    and (not status_filter or get_status(item, now) in status_filter)
    and (not location_keys or normalize_location(item.location) in location_keys)
]
visible.sort(key=SORT_OPTIONS[sort_by], reverse=descending)

tab_list, tab_gantt = st.tabs(["📋 목록", "📊 간트 차트"])

# ---------------------------------------------------------------- 목록 + 선택 작업 (F2·F3·F4·F7)
with tab_list:
    if not visible:
        st.info("필터 조건에 맞는 아이템이 없습니다. 필터를 조정해 보세요.", icon="🔍")
    else:
        st.caption(f"{len(visible)}건 표시 / 전체 {len(items)}건 · 행 왼쪽 체크박스로 선택한 뒤 아래 버튼으로 수정·삭제합니다.")
        # 필터·정렬이 바뀌면 표 key도 바뀌어 선택이 초기화된다 → 화면 순서와 선택 인덱스가 어긋나지 않는다
        filter_signature = hash((tuple(type_filter), tuple(status_filter), tuple(location_filter), sort_by, descending))
        with st.container(key="item_table"):
            event = st.dataframe(
                display_frame(visible),
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key=f"item_table_{table_version()}_{filter_signature}",
                width="stretch",
                column_config={
                    "공사 이름": st.column_config.TextColumn(width="medium"),
                    "구분": st.column_config.TextColumn(width="small"),
                    "시작일": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "종료일": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "기간(일)": st.column_config.NumberColumn(format="%d일", width="small"),
                    "진행률": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                    "재분배": st.column_config.TextColumn(width=100),
                    "원래 일정": st.column_config.TextColumn(width="medium", help="재분배 전 원래 설치 일정"),
                },
            )
        selected = [visible[i] for i in event.selection.rows if i < len(visible)]
        rescheduled = [i for i in selected if i.rescheduled]

        cols = st.columns([1, 1, 1.6, 0.8], vertical_alignment="center")
        if cols[0].button("수정", icon=":material/edit:", key="edit_selected_button", disabled=len(selected) != 1, width="stretch"):
            open_item_dialog(selected[0])
        if cols[1].button(
            f"삭제 ({len(selected)})", icon=":material/delete:", key="delete_selected_button", disabled=not selected, width="stretch"
        ):
            open_delete_dialog([i.id for i in selected])
        if cols[2].button(
            "원래 일정으로 되돌리기", icon=":material/undo:", key="revert_button", disabled=not rescheduled, width="stretch"
        ):
            targets = {i.id for i in rescheduled}
            modify(lambda latest: [revert_to_original(i) if i.id in targets else i for i in latest])
            flash(f"{len(targets)}건을 원래 일정으로 되돌렸습니다.", icon="↩️")
            st.rerun()
        if not selected:
            st.caption("수정은 1건, 삭제는 여러 건 선택할 수 있습니다.")
        elif not rescheduled:
            st.caption("되돌리기는 🔁 재분배된 아이템에만 쓸 수 있습니다.")

# ---------------------------------------------------------------- 간트 차트 (F2 권장)
with tab_gantt:
    if not visible:
        st.info("필터 조건에 맞는 아이템이 없습니다.", icon="🔍")
    else:
        st.caption("장소별로 묶어 표시합니다. 빗금 막대는 재분배 전 원래 일정, 붉은 점선은 오늘입니다.")
        st.plotly_chart(build_gantt(visible, now), key="gantt_chart", width="stretch")
