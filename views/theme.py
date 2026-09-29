"""화면 색상·아이콘 규칙 (3단계). 색만으로 구분하지 않도록 항상 아이콘/텍스트를 함께 쓴다."""

import re

from core.models import ItemStatus, ItemType

# 구분 색 — 라이트/다크 배경 모두에서 대비가 충분한 중간 명도
TYPE_COLORS: dict[ItemType, str] = {"제작": "#D97706", "설치": "#2563EB"}
TYPE_ICONS: dict[ItemType, str] = {"제작": "🏭", "설치": "🔧"}

STATUS_ICONS: dict[ItemStatus, str] = {"예정": "🟦", "진행중": "🟨", "완료": "🟩", "지연": "🟥"}
STATUS_HELP: dict[ItemStatus, str] = {
    "예정": "시작 전이고 진행률 0%",
    "진행중": "기간 중이거나 진행률이 0%보다 큼",
    "완료": "진행률 100%",
    "지연": "종료일이 지났는데 진행률 100% 미만",
}

RESCHEDULED_LABEL = "🔁 재분배"
TODAY_LINE_COLOR = "#DC2626"
GHOST_COLOR = "rgba(128, 128, 128, 0.55)"


def status_label(status: ItemStatus) -> str:
    return f"{STATUS_ICONS[status]} {status}"


def type_label(item_type: ItemType) -> str:
    return f"{TYPE_ICONS[item_type]} {item_type}"


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md(text: object) -> str:
    """사용자가 입력한 문자열을 마크다운 문법으로 해석되지 않게 이스케이프한다.

    (예: '**굵게**', ':red[글자]', '<b>' 가 공사 이름에 있어도 입력한 그대로 보이게)
    """
    return _MD_SPECIAL.sub(r"\\\1", str(text))


# 업로드 미리보기 편집표의 열 순서와 너비(px). 너비를 고정해 화면이 파일 내용에 따라 흔들리지 않게 하고,
# E2E 테스트가 칸 위치를 계산하는 데도 같은 값을 쓴다.
PREVIEW_COLUMN_WIDTHS: dict[str, int] = {
    "상태": 80,
    "오류": 230,
    "제외": 60,
    "선택": 60,
    "행": 50,
    "공사 이름": 170,
    "공사 장소": 130,
    "구분": 80,
    "시작일": 110,
    "종료일": 110,
}
