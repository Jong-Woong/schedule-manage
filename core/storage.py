"""로컬 JSON 파일 저장소 (PRD 6장 데이터 저장)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.models import Item

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "items.json"


# 한 Streamlit 서버 안의 여러 브라우저 탭(세션)은 같은 프로세스의 스레드다 → 읽기-수정-쓰기를 잠금으로 묶는다
_LOCK = threading.RLock()


def data_path() -> Path:
    """저장 파일 경로. 환경 변수 APP_DATA_PATH가 있으면 그 값을 사용한다 (테스트용)."""
    return Path(os.environ.get("APP_DATA_PATH") or DEFAULT_DATA_PATH)


@dataclass
class LoadResult:
    items: list[Item] = field(default_factory=list)
    warning: str | None = None
    """파일 손상 등으로 빈 목록으로 시작한 경우의 안내 메시지"""


def load_items(path: Path | None = None) -> LoadResult:
    """저장 파일을 읽는다. 파일이 없으면 빈 목록, 손상되었으면 .bak으로 백업 후 빈 목록 + 경고."""
    path = path or data_path()
    if not path.exists():
        return LoadResult()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("최상위 값이 목록이 아닙니다.")
        return LoadResult(items=[Item.from_dict(entry) for entry in raw])
    except (ValueError, KeyError, TypeError) as exc:
        backup = path.with_name(f"{path.stem}.{datetime.now():%Y%m%d%H%M%S}.bak")
        path.replace(backup)
        return LoadResult(
            warning=f"저장 파일이 손상되어 빈 목록으로 시작합니다. 기존 파일은 {backup.name}으로 백업했습니다. ({exc})"
        )


def save_items(items: list[Item], path: Path | None = None) -> None:
    """임시 파일에 쓴 뒤 교체하여, 저장 도중 중단되어도 기존 파일이 깨지지 않게 한다."""
    path = path or data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def file_signature(path: Path | None = None) -> tuple[int, int] | None:
    """저장 파일의 (수정 시각, 크기). 다른 탭에서 파일이 바뀌었는지 판단하는 데 쓴다. 파일이 없으면 None."""
    path = path or data_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def modify_items(mutator: Callable[[list[Item]], list[Item]], path: Path | None = None) -> list[Item]:
    """파일에서 최신 목록을 읽어 mutator 로 바꾼 뒤 저장한다 (읽기-수정-쓰기를 잠금 안에서).

    화면이 들고 있던 목록이 아니라 저장 직전의 최신 파일을 기준으로 바꾸므로,
    다른 탭에서 추가·삭제한 내용을 덮어쓰지 않는다.
    """
    with _LOCK:
        current = load_items(path).items
        updated = mutator(current)
        save_items(updated, path)
        return updated
