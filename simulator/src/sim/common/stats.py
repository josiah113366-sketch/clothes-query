"""실행기 숫자 파일. member·behavior live가 누적 숫자를 쓰고 컨트롤러 화면이 읽는다.

제어 파일과 같은 폴더(ECS에서는 공유 볼륨 /control)에 stats-<이름>.json으로 둔다.
숫자와 모드만 담는다(PII 없음). 쓰기가 실패해도 실행기는 멈추지 않는다.
"""

import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

STATS_SECONDS = 2.0  # 쓰기 주기 (실제 시간)


def stats_path(control_file: Path, name: str) -> Path:
    return control_file.parent / f"stats-{name}.json"


def write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    """읽는 쪽이 반쯤 쓴 파일을 보지 않도록 임시 파일에 쓴 뒤 os.replace로 바꾼다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data) + "\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


class StatsFile:
    """누적 숫자를 쓴다. written_at(epoch 초)을 붙인다. 실패는 한 번만 알리고 넘어간다."""

    def __init__(
        self,
        path: Path,
        warn: Callable[[str], None] = print,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self._warn = warn
        self._now = now
        self._warned = False

    def write(self, data: Mapping[str, Any]) -> None:
        try:
            write_json_atomic(self.path, {"written_at": self._now(), **data})
        except OSError:
            if not self._warned:
                self._warned = True
                self._warn(f"숫자 파일({self.path.name})을 쓰지 못했습니다. 실행은 계속합니다.")
        else:
            self._warned = False


def read_stats(path: Path) -> dict[str, Any] | None:
    """읽을 수 없거나 JSON 객체가 아니면 None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
