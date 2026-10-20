"""정답표(incident_log) 기록기. 레코드 하나 = 파일(또는 S3 객체) 하나.

기록은 끝까지 성공해야 돌아온다. 실패하면 IncidentLogError를 올린다.
메시지에는 버킷 이름, 키, 자격 증명을 싣지 않는다.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from botocore.exceptions import BotoCoreError, ClientError

from sim.controller.model import file_stamp

S3_PREFIX = "ground_truth/incident_log/"
DEFAULT_INCIDENT_DIR = ".local/incident_log"


class IncidentLogError(RuntimeError):
    """정답표를 쓰지 못했다."""


class IncidentLog(Protocol):
    def write(self, record: dict) -> None:
        """기록이 끝까지 성공해야 돌아온다. 실패하면 IncidentLogError."""
        ...


def record_filename(record: dict) -> str:
    """YYYYMMDDTHHMMSSZ_<incident_id>_<phase>.json"""
    at = datetime.strptime(record["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return f"{file_stamp(at)}_{record['incident_id']}_{record['phase']}.json"


def record_bytes(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


class FileIncidentLog:
    """로컬 폴더. 임시 파일에 쓰고 fsync한 뒤 os.replace한다. 같은 파일을 덮어쓰지 않는다."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(self, record: dict) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / record_filename(record)
            if target.exists():
                raise IncidentLogError(f"같은 정답표 파일이 이미 있습니다: {target.name}")
            fd, temp = tempfile.mkstemp(dir=self.directory, prefix=".", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(record_bytes(record))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, target)
            except BaseException:
                Path(temp).unlink(missing_ok=True)
                raise
        except OSError as error:
            raise IncidentLogError(
                f"정답표 파일을 쓰지 못했습니다 ({type(error).__name__})"
            ) from None


class S3IncidentLog:
    """키 ground_truth/incident_log/<파일명>으로 put_object한다. client를 주입할 수 있다."""

    def __init__(
        self, bucket: str, client: object | None = None, region: str | None = None
    ) -> None:
        if not bucket:
            raise ValueError("S3 버킷이 비어 있습니다.")
        self._bucket = bucket
        self._client = client
        self._region = region

    def _get_client(self) -> object:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def write(self, record: dict) -> None:
        key = S3_PREFIX + record_filename(record)
        try:
            self._get_client().put_object(  # type: ignore[attr-defined]
                Bucket=self._bucket,
                Key=key,
                Body=record_bytes(record),
                ContentType="application/json",
            )
        except ClientError as error:  # 응답 본문·버킷·키는 싣지 않고 오류 코드만
            code = error.response.get("Error", {}).get("Code", "unknown")
            raise IncidentLogError(f"정답표를 S3에 쓰지 못했습니다 (오류 코드 {code})") from None
        except (BotoCoreError, OSError) as error:
            raise IncidentLogError(
                f"정답표를 S3에 쓰지 못했습니다 ({type(error).__name__})"
            ) from None


class MemoryIncidentLog:
    """테스트용. fail_next만큼 다음 쓰기를 실패시킨다."""

    def __init__(self) -> None:
        self.records: list[dict] = []
        self.fail_next = 0

    def write(self, record: dict) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise IncidentLogError("정답표 기록 실패 (테스트)")
        self.records.append(dict(record))
