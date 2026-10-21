"""제어 신호를 받는 쪽 인터페이스와 로컬 개발용 파일 구현.

실제 전달 수단(HTTP, 큐 등)은 아직 정해지지 않았다. 파일 방식은 로컬용이다.
회원 실행기는 컨트롤러 모듈을 import하지 않고 이 인터페이스만 본다.
"""

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

MODES: tuple[str, ...] = ("normal", "medium", "burst")
DEFAULT_CONTROL_FILE = ".local/control.json"


@dataclass(frozen=True)
class ControlState:
    running: bool  # False면 가입 생성을 멈춘다 (프로세스는 살아 있음)
    mode: str  # "normal" | "medium" | "burst"
    # PG 이름 → 그 PG의 PG 원인 실패 확률 추가분 (0~1). 없으면 빈 값. common은 PG 이름을 모른다
    pg_extra_fail: Mapping[str, float] = field(default_factory=dict, hash=False)


class ControlSource(Protocol):
    def read(self) -> ControlState | None:
        """읽을 수 없으면 None (호출한 쪽은 마지막 상태를 유지한다)."""
        ...


def _parse(text: str) -> ControlState:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("JSON 객체가 아닙니다.")
    running, mode = data.get("running"), data.get("mode")
    if not isinstance(running, bool):
        raise TypeError("running은 true/false여야 합니다.")
    if mode not in MODES:
        raise ValueError(f"mode는 {', '.join(MODES)} 중 하나여야 합니다.")
    return ControlState(running=running, mode=mode, pg_extra_fail=_parse_extra(data))


def _parse_extra(data: dict) -> dict[str, float]:
    """선택 항목 pg_extra_fail: {PG 이름: 0 이상 1 이하의 숫자}. 틀리면 파일 전체가 잘못된 값이다."""
    raw = data.get("pg_extra_fail", {})
    if not isinstance(raw, dict):
        raise TypeError("pg_extra_fail은 객체여야 합니다.")
    extra: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("pg_extra_fail의 값은 숫자여야 합니다.")
        if not (math.isfinite(value) and 0 <= value <= 1):
            raise ValueError("pg_extra_fail의 값은 0 이상 1 이하여야 합니다.")
        extra[str(name)] = float(value)
    return extra


def _warn_stderr(message: str) -> None:
    print(f"경고: {message}", flush=True)


class FileControlSource:
    """JSON 파일 {"running": true, "mode": "burst", "pg_extra_fail": {"PG_B": 0.85}}를 읽는다.

    pg_extra_fail은 없어도 된다. 로컬 개발용이다.
    """

    def __init__(self, path: Path, warn: Callable[[str], None] = _warn_stderr) -> None:
        self.path = path
        self._warn = warn
        self._warned = False

    def read(self) -> ControlState | None:
        try:
            state = _parse(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._fail("파일이 없습니다")
        except (OSError, UnicodeDecodeError):
            self._fail("파일을 읽을 수 없습니다")
        except (ValueError, TypeError):  # JSON 깨짐 포함. 메시지에 파일 내용을 싣지 않는다
            self._fail("내용이 올바르지 않습니다")
        else:
            self._warned = False
            return state
        return None

    def _fail(self, reason: str) -> None:
        if not self._warned:  # 같은 문제가 이어지는 동안 한 번만
            self._warned = True
            self._warn(f"제어 파일({self.path.name}) {reason}. 마지막 상태를 유지합니다.")
