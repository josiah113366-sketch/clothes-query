"""제어 신호를 받는 쪽 인터페이스와 로컬 개발용 파일 구현.

실제 전달 수단(HTTP, 큐 등)은 아직 정해지지 않았다. 파일 방식은 로컬용이다.
회원 실행기는 컨트롤러 모듈을 import하지 않고 이 인터페이스만 본다.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MODES: tuple[str, ...] = ("normal", "medium", "burst")
DEFAULT_CONTROL_FILE = ".local/control.json"


@dataclass(frozen=True)
class ControlState:
    running: bool  # False면 가입 생성을 멈춘다 (프로세스는 살아 있음)
    mode: str  # "normal" | "medium" | "burst"


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
    return ControlState(running=running, mode=mode)


def _warn_stderr(message: str) -> None:
    print(f"경고: {message}", flush=True)


class FileControlSource:
    """JSON 파일 {"running": true, "mode": "burst"}를 읽는다 (로컬 개발용)."""

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
