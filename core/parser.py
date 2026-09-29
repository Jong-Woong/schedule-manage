"""PRD 4장 F6 공정표 파일 업로드 및 자동 인식."""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import PurePath
from typing import Any, Literal

import pandas as pd

from core.dates import today
from core.items import validate_item_input
from core.models import ItemType

MappableField = Literal["name", "location", "type", "start_date", "end_date", "period"]

FIELD_LABELS: dict[MappableField, str] = {
    "name": "공사 이름",
    "location": "공사 장소",
    "type": "구분",
    "start_date": "시작일",
    "end_date": "종료일",
    "period": "기간(시작~종료)",
}

SUPPORTED_EXTENSIONS = (".xlsx", ".xls", ".csv")

# PRD 6.2 인식 키워드 (공백 제거·소문자 기준)
# 1차: 헤더 전체가 키워드와 정확히 일치 / 2차: 헤더에 키워드가 포함 (위 순서대로 우선)
_EXACT_KEYWORDS: dict[MappableField, tuple[str, ...]] = {
    "name": ("공사명", "공사이름", "공종", "작업명", "항목", "name", "공사", "작업"),
    "location": ("장소", "공사장소", "위치", "설치위치", "설치장소", "구역", "동/층", "location"),
    "type": ("구분", "유형", "종류", "type"),
    "start_date": ("시작", "시작일", "착수일", "착수", "start", "시작일자"),
    "end_date": ("종료", "종료일", "완료일", "완료", "end", "종료일자"),
    "period": ("기간", "일정", "period", "공기"),
}
_CONTAINS_ORDER: tuple[tuple[MappableField, tuple[str, ...]], ...] = (
    ("location", ("장소", "위치", "구역", "location")),
    ("start_date", ("시작", "착수", "start")),
    ("end_date", ("종료", "완료", "end")),
    ("period", ("기간", "일정", "period")),
    ("type", ("구분", "유형", "type")),
    ("name", ("공사명", "공사이름", "작업명", "공종", "name")),
)

_TYPE_KEYWORDS: tuple[tuple[ItemType, tuple[str, ...]], ...] = (
    ("제작", ("제작", "제조", "가공")),
    ("설치", ("설치", "시공", "현장")),
)

# '완료 여부', '시작 비고' 같은 열은 날짜 열이 아니다 (B6)
_NOT_DATE_WORDS = ("여부", "비고", "메모", "담당")
_DATE_FIELDS = ("start_date", "end_date", "period")

_HEADER_SCAN_ROWS = 10
_EXCEL_EPOCH = date(1899, 12, 30)


class ScheduleParseError(Exception):
    """파일 자체를 읽을 수 없을 때 (형식 오류, 빈 파일, 헤더 없음 등)."""


@dataclass
class ParsedRow:
    row_number: int
    """원본 파일에서의 행 번호 (1부터, 엑셀에서 보이는 번호)"""
    raw: list[Any]
    """원본 셀 값"""
    values: dict[str, Any] = field(default_factory=dict)
    """인식된 값: name, location, type, start_date, end_date (인식 실패 시 None)"""
    errors: list[str] = field(default_factory=list)
    """인식 실패 사유 (빈 목록이면 정상 행)"""


@dataclass
class Table:
    headers: list[str]
    header_row_number: int
    """헤더가 있는 원본 행 번호 (1부터)"""
    rows: list[list[Any]]
    """헤더 아래 데이터 행 (원본 값)"""


@dataclass
class ParseResult:
    table: Table
    mapping: dict[MappableField, int]
    """필드 → 원본 열 인덱스"""
    rows: list[ParsedRow]

    @property
    def headers(self) -> list[str]:
        return self.table.headers


# ---------------------------------------------------------------- 파일 읽기


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text)).lower()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    return isinstance(value, str) and not value.strip()


def _read_csv(file_bytes: bytes) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False, skip_blank_lines=False)
    raise ScheduleParseError("CSV 파일의 문자 인코딩을 인식할 수 없습니다. (UTF-8 또는 CP949로 저장해 주세요)")


def _read_raw(file_bytes: bytes, filename: str) -> pd.DataFrame:
    ext = PurePath(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ScheduleParseError(f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'} — .xlsx / .xls / .csv 파일만 가능합니다.")
    if not file_bytes:
        raise ScheduleParseError("빈 파일입니다.")
    try:
        if ext == ".csv":
            return _read_csv(file_bytes)
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"
        # 여러 시트가 있으면 첫 번째 시트만 읽는다
        return pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=object, engine=engine)
    except ScheduleParseError:
        raise
    except pd.errors.EmptyDataError as exc:
        raise ScheduleParseError("빈 파일입니다.") from exc
    except Exception as exc:  # 손상 파일, 확장자만 바꾼 파일 등
        raise ScheduleParseError(f"파일을 읽을 수 없습니다. 파일이 손상되었거나 형식이 맞지 않습니다. ({exc})") from exc


def _cells(df: pd.DataFrame) -> list[list[Any]]:
    return [[None if _is_blank(v) else v for v in row] for row in df.itertuples(index=False, name=None)]


def detect_mapping(headers: list[str]) -> dict[MappableField, int]:
    """헤더 이름을 키워드로 매칭해 필드 → 열 인덱스를 만든다. 한 열은 한 필드에만 매핑된다."""
    normalized = [_norm(h) for h in headers]
    mapping: dict[MappableField, int] = {}
    used: set[int] = set()

    for field_name, keywords in _EXACT_KEYWORDS.items():
        for index, header in enumerate(normalized):
            if index not in used and header in keywords:
                mapping[field_name] = index
                used.add(index)
                break

    for field_name, keywords in _CONTAINS_ORDER:
        if field_name in mapping:
            continue
        for index, header in enumerate(normalized):
            if field_name in _DATE_FIELDS and any(word in header for word in _NOT_DATE_WORDS):
                continue
            if index not in used and header and any(k in header for k in keywords):
                mapping[field_name] = index
                used.add(index)
                break

    # 시작/종료 열이 있으면 기간 열은 쓰지 않는다
    if "start_date" in mapping and "end_date" in mapping:
        mapping.pop("period", None)
    return mapping


def read_table(file_bytes: bytes, filename: str) -> Table:
    """파일을 읽고 헤더 행을 찾는다. 헤더가 첫 행이 아니어도 위쪽 10행 안에서 찾는다."""
    rows = _cells(_read_raw(file_bytes, filename))
    if not any(any(v is not None for v in row) for row in rows):
        raise ScheduleParseError("파일에 내용이 없습니다.")

    best_index, best_score = -1, 0
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        headers = ["" if v is None else str(v).strip() for v in row]
        score = len(detect_mapping(headers))
        if score > best_score:
            best_index, best_score = index, score
    if best_score < 2:
        raise ScheduleParseError(
            "헤더(열 이름)를 찾을 수 없습니다. 첫 행에 '공사명, 장소, 구분, 시작일, 종료일' 같은 열 이름이 있어야 합니다."
        )

    headers = ["" if v is None else str(v).strip() for v in rows[best_index]]
    headers = [h or f"(열 {i + 1})" for i, h in enumerate(headers)]
    return Table(headers=headers, header_row_number=best_index + 1, rows=rows[best_index + 1 :])


# ---------------------------------------------------------------- 값 인식


_YMD = re.compile(r"^(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*[.일]?$")
_YMD_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_MD = re.compile(r"^(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*[.일]?$")
_SERIAL = re.compile(r"^\d{5}(\.0+)?$")
_TIME_SUFFIX = re.compile(r"[ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?$")


def _from_serial(value: float) -> date | None:
    if 20000 <= value <= 80000:  # 1954 ~ 2119년 범위만 날짜로 인정
        return _EXCEL_EPOCH + timedelta(days=int(value))
    return None


def parse_date(value: Any) -> date | None:
    """PRD 6.2 날짜 형식 인식. 인식할 수 없으면 ValueError, 빈 값이면 None."""
    if _is_blank(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        raise ValueError(str(value))
    if isinstance(value, (int, float)):
        result = _from_serial(float(value))
        if result is None:
            raise ValueError(str(value))
        return result

    text = _TIME_SUFFIX.sub("", str(value).strip())
    try:
        if m := _YMD.match(text) or _YMD_COMPACT.match(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := _MD.match(text):
            return date(today().year, int(m[1]), int(m[2]))
        if _SERIAL.match(text) and (result := _from_serial(float(text))):
            return result
    except ValueError:  # 2026-13-45 같은 존재하지 않는 날짜
        pass
    raise ValueError(text)


def _is_yearless(value: Any) -> bool:
    """연도 없이 'MM/DD' 형식으로 쓴 날짜인지."""
    return isinstance(value, str) and bool(_MD.match(_TIME_SUFFIX.sub("", value.strip())))


def parse_type(value: Any) -> ItemType | None:
    """구분 값 인식: 제작/제조/가공 → 제작, 설치/시공/현장 → 설치. 인식 실패 시 None."""
    if _is_blank(value):
        return None
    text = _norm(value)
    for item_type, keywords in _TYPE_KEYWORDS:
        if any(k in text for k in keywords):
            return item_type
    return None


def _split_period(value: Any) -> tuple[Any, Any]:
    if _is_blank(value):
        return None, None
    parts = re.split(r"\s*[~～〜]\s*", str(value).strip())
    if len(parts) != 2:
        return value, None
    return parts[0], parts[1]


def _text(value: Any) -> str:
    if _is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def validate_values(values: dict[str, Any]) -> list[str]:
    """인식된 값의 오류 사유 목록. 미리보기에서 사용자가 값을 고친 뒤에도 다시 사용한다."""
    return validate_item_input(
        name=values.get("name") or "",
        location=values.get("location") or "",
        type_=values.get("type"),
        start_date=values.get("start_date"),
        end_date=values.get("end_date"),
        progress=0,
    )


def recognize_rows(table: Table, mapping: dict[MappableField, int]) -> list[ParsedRow]:
    """매핑에 따라 각 행을 인식한다. 모든 셀이 빈 행은 건너뛴다."""

    def cell(row: list[Any], field_name: MappableField) -> Any:
        index = mapping.get(field_name)
        return row[index] if index is not None and index < len(row) else None

    parsed: list[ParsedRow] = []
    for offset, row in enumerate(table.rows):
        if all(_is_blank(v) for v in row):
            continue

        errors: list[str] = []
        raw_type = cell(row, "type")
        item_type = parse_type(raw_type)

        start_raw, end_raw = cell(row, "start_date"), cell(row, "end_date")
        if "start_date" not in mapping and "end_date" not in mapping:
            start_raw, end_raw = _split_period(cell(row, "period"))

        dates: dict[str, date | None] = {}
        for key, raw_value, label in (("start_date", start_raw, "시작일"), ("end_date", end_raw, "종료일")):
            try:
                dates[key] = parse_date(raw_value)
            except ValueError:
                dates[key] = None
                errors.append(f"{label} 형식을 인식할 수 없습니다: '{_text(raw_value)}'")

        # 연도 없이 쓴 날짜가 해를 넘기면(12/28~01/05) 종료일을 다음 해로 본다 (B5)
        start, end = dates["start_date"], dates["end_date"]
        if start and end and end < start and _is_yearless(end_raw):
            try:
                dates["end_date"] = end.replace(year=end.year + 1)
            except ValueError:  # 02/29 → 다음 해에 없는 날짜
                pass

        values = {
            "name": _text(cell(row, "name")),
            "location": _text(cell(row, "location")),
            "type": item_type,
            **dates,
        }
        # 형식 오류가 이미 기록된 날짜는 "입력하세요" 메시지를 중복으로 넣지 않는다
        for message in validate_values(values):
            if message.startswith(("시작일을", "종료일을")) and any(e.startswith(message[:3]) for e in errors):
                continue
            if message.startswith("구분") and not _is_blank(raw_type):
                message = f"구분 값을 인식할 수 없습니다: '{_text(raw_type)}' (제작/설치)"
            errors.append(message)

        parsed.append(
            ParsedRow(
                row_number=table.header_row_number + offset + 1,
                raw=list(row),
                values=values,
                errors=errors,
            )
        )
    return parsed


def parse_schedule_file(file_bytes: bytes, filename: str) -> ParseResult:
    """.xlsx / .xls / .csv 공정표를 읽어 헤더 키워드로 열을 매핑하고 행 단위로 인식한다.

    파일 자체를 읽을 수 없으면 ScheduleParseError.
    """
    table = read_table(file_bytes, filename)
    mapping = detect_mapping(table.headers)
    return ParseResult(table=table, mapping=mapping, rows=recognize_rows(table, mapping))
