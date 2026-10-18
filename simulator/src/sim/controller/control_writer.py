"""제어 파일 쓰기. member live와 behavior live가 같은 파일을 1초마다 읽는다.

읽는 쪽이 반쯤 쓴 파일을 보지 않도록 같은 폴더의 임시 파일에 쓴 뒤 os.replace로 바꾼다.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from sim.common.control import MODES, ControlState, FileControlSource


class ControlWriter(Protocol):
    def write(self, running: bool, mode: str, pg_extra_fail: Mapping[str, float]) -> None: ...

    def read_current(self) -> ControlState | None: ...


class FileControlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, running: bool, mode: str, pg_extra_fail: Mapping[str, float]) -> None:
        if mode not in MODES:
            raise ValueError(f"mode는 {', '.join(MODES)} 중 하나여야 합니다.")
        data = {
            "running": running,
            "mode": mode,
            "pg_extra_fail": dict(sorted(pg_extra_fail.items())),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".control-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    def read_current(self) -> ControlState | None:
        """컨트롤러 안에서 지금 값을 확인하는 용도. 읽을 수 없으면 None."""
        return FileControlSource(self.path, warn=lambda _: None).read()


class MemoryControlWriter:
    """테스트용. 쓴 값을 순서대로 쌓는다."""

    def __init__(self) -> None:
        self.writes: list[ControlState] = []
        self.fail_next = 0

    def write(self, running: bool, mode: str, pg_extra_fail: Mapping[str, float]) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise OSError("제어 파일 쓰기 실패 (테스트)")
        self.writes.append(ControlState(running, mode, dict(pg_extra_fail)))

    def read_current(self) -> ControlState | None:
        return self.writes[-1] if self.writes else None
