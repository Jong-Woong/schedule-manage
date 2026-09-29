"""간트 차트 (PRD F2 권장, 3단계 디자인).

- 장소별로 행을 묶는다 (Plotly multicategory 축: 장소 > 공사)
- 제작/설치 색 구분, 오늘 날짜 세로선
- 재분배된 공사는 원래 위치를 빗금 친 반투명 막대로 함께 표시
"""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go

from core.items import get_duration, location_labels, normalize_location
from core.models import ITEM_TYPES, Item
from views.theme import GHOST_COLOR, TODAY_LINE_COLOR, TYPE_COLORS

_DAY_MS = 24 * 60 * 60 * 1000


def _span_ms(start: date, end: date) -> int:
    """종료일 당일까지 막대가 보이도록 (종료일 + 1일 - 시작일)."""
    return ((end - start).days + 1) * _DAY_MS


def build_gantt(items: list[Item], today: date) -> go.Figure:
    # 공백·대소문자만 다른 장소는 한 그룹으로 묶고, 처음 등록된 표기로 보여준다 (B2)
    labels = location_labels(items)
    ordered = sorted(items, key=lambda i: (labels[normalize_location(i.location)], i.start_date, i.name))
    y_location = [labels[normalize_location(i.location)] for i in ordered]
    y_name: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for loc, item in zip(y_location, ordered):
        label = f"{item.name} · {item.type}"
        count = seen[(loc, label)] = seen.get((loc, label), 0) + 1
        # 같은 장소에 이름·구분이 같은 공사가 여러 개면 한 줄로 합쳐지지 않게 번호를 붙인다
        y_name.append(label if count == 1 else f"{label} ({count})")

    fig = go.Figure()
    # 행 순서 고정용 보이지 않는 막대 (multicategory 축은 처음 나온 순서대로 행을 만든다)
    fig.add_bar(
        orientation="h", y=[y_location, y_name], x=[0] * len(ordered), base=[i.start_date.isoformat() for i in ordered],
        showlegend=False, hoverinfo="skip", marker=dict(color="rgba(0,0,0,0)"),
    )

    # 원래 위치 (재분배된 공사만) — 먼저 그려서 실제 막대 아래에 깔린다
    ghosts = [(n, i) for n, i in enumerate(ordered) if i.rescheduled and i.original_start_date and i.original_end_date]
    if ghosts:
        fig.add_bar(
            name="원래 일정 (재분배 전)",
            orientation="h",
            y=[[y_location[n] for n, _ in ghosts], [y_name[n] for n, _ in ghosts]],
            base=[i.original_start_date.isoformat() for _, i in ghosts],
            x=[_span_ms(i.original_start_date, i.original_end_date) for _, i in ghosts],
            marker=dict(color="rgba(0,0,0,0)", line=dict(color=GHOST_COLOR, width=1.5), pattern=dict(shape="/", fgcolor=GHOST_COLOR, size=6)),
            customdata=[[i.name, i.original_start_date, i.original_end_date] for _, i in ghosts],
            hovertemplate="<b>%{customdata[0]}</b><br>원래 일정: %{customdata[1]} ~ %{customdata[2]}<extra></extra>",
        )

    for item_type in ITEM_TYPES:
        rows = [(n, i) for n, i in enumerate(ordered) if i.type == item_type]
        if not rows:
            continue
        fig.add_bar(
            name=item_type,
            orientation="h",
            y=[[y_location[n] for n, _ in rows], [y_name[n] for n, _ in rows]],
            base=[i.start_date.isoformat() for _, i in rows],
            x=[_span_ms(i.start_date, i.end_date) for _, i in rows],
            marker=dict(color=TYPE_COLORS[item_type]),
            text=[f"{i.progress}%" for _, i in rows],
            textposition="inside",
            insidetextanchor="start",
            customdata=[
                [i.name, i.location, i.start_date, i.end_date, get_duration(i), i.progress, "재분배됨" if i.rescheduled else ""]
                for _, i in rows
            ],
            hovertemplate=(
                "<b>%{customdata[0]}</b> %{customdata[6]}<br>"
                "장소: %{customdata[1]}<br>"
                "일정: %{customdata[2]} ~ %{customdata[3]} (%{customdata[4]}일)<br>"
                "진행률: %{customdata[5]}%<extra></extra>"
            ),
        )

    fig.add_shape(
        type="line", x0=today.isoformat(), x1=today.isoformat(), y0=0, y1=1, yref="paper",
        line=dict(color=TODAY_LINE_COLOR, width=2, dash="dot"),
    )
    fig.add_annotation(
        x=today.isoformat(), y=1, yref="paper", yanchor="bottom", text=f"오늘 {today:%m/%d}",
        showarrow=False, font=dict(color=TODAY_LINE_COLOR, size=12),
    )

    first = min(min(i.start_date for i in ordered), today)
    last = max(max(i.end_date for i in ordered), today)
    fig.update_layout(
        barmode="overlay",
        height=max(280, 36 * len(ordered) + 140),
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1, title=None),
        bargap=0.35,
        hoverlabel=dict(align="left"),
    )
    fig.update_xaxes(
        type="date",
        range=[(first - timedelta(days=1)).isoformat(), (last + timedelta(days=2)).isoformat()],
        tickformat="%m/%d",
        showgrid=True,
    )
    fig.update_yaxes(autorange="reversed", title=None, showdividers=True)
    return fig
