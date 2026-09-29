"""PRD 6장 내보내기: 현재 공정 목록을 엑셀(.xlsx)로 만든다."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

from core.items import get_duration, get_status
from core.models import Item


DATE_COLUMNS = ("시작일", "종료일", "원래 시작일", "원래 종료일")


def items_to_frame(items: list[Item], today: date) -> pd.DataFrame:
    """목록 화면·내보내기 공용 표 (한글 컬럼명). 날짜 열은 datetime(빈 값은 NaT)."""
    frame = pd.DataFrame(
        [
            {
                "공사 이름": item.name,
                "공사 장소": item.location,
                "구분": item.type,
                "시작일": item.start_date,
                "종료일": item.end_date,
                "기간(일)": get_duration(item),
                "진행률(%)": item.progress,
                "상태": get_status(item, today),
                "재분배": "재분배" if item.rescheduled else "",
                "원래 시작일": item.original_start_date,
                "원래 종료일": item.original_end_date,
            }
            for item in items
        ],
        columns=["공사 이름", "공사 장소", "구분", "시작일", "종료일", "기간(일)", "진행률(%)", "상태", "재분배", "원래 시작일", "원래 종료일"],
    )
    for column in DATE_COLUMNS:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def export_xlsx(items: list[Item], today: date) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        items_to_frame(items, today).to_excel(writer, index=False, sheet_name="공정 목록")
        sheet = writer.sheets["공정 목록"]
        for column in ("D", "E", "J", "K"):
            for cell in sheet[column][1:]:
                cell.number_format = "yyyy-mm-dd"
            sheet.column_dimensions[column].width = 12
        sheet.column_dimensions["A"].width = 24
        sheet.column_dimensions["B"].width = 16
    return buffer.getvalue()
