"""S3 읽기 전용 도우미 (boto3). 쓰기·삭제 함수를 만들지 않는다.

오류 메시지에는 분류된 이유만 싣는다. boto3의 원문 메시지에는 버킷 이름·ARN·요청 ID가 섞일 수 있어
그대로 내보내지 않는다. 자격 증명 값과 버킷 이름은 어떤 출력에도 없다.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    NoRegionError,
)

from sim.sink import params

_DENIED = {"AccessDenied", "AllAccessDisabled", "AccountProblem"}
_NO_KEY = {"InvalidAccessKeyId", "SignatureDoesNotMatch", "InvalidToken", "ExpiredToken"}


class S3Error(RuntimeError):
    """S3 호출 실패. 메시지는 이유 분류만 담는다."""


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int
    last_modified: datetime


def describe_error(error: Exception) -> str:
    """오류를 이유 한 줄로 바꾼다 (키 값·버킷 이름 없음)."""
    if isinstance(error, NoCredentialsError):
        return "자격 증명이 없습니다 (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY를 simulator/.env에 두세요)"
    if isinstance(error, NoRegionError):
        return "리전이 없습니다 (AWS_REGION)"
    if isinstance(error, EndpointConnectionError):
        return "S3에 닿지 않습니다 (네트워크 또는 리전)"
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchBucket", "404"}:
            return "버킷이 없습니다"
        if code in _NO_KEY:
            return f"자격 증명이 거부됐습니다 ({code})"
        if code in _DENIED or code == "403":
            return "권한이 없습니다 (AccessDenied)"
        if code in {"PermanentRedirect", "AuthorizationHeaderMalformed", "301"}:
            return "리전이 버킷과 다릅니다"
        return f"S3 오류 (code={code or '알 수 없음'})"
    if isinstance(error, BotoCoreError):
        return f"S3 호출 실패 ({type(error).__name__})"
    return f"S3 호출 실패 ({type(error).__name__})"


class S3Reader:
    def __init__(self, bucket: str, region: str, client: Any | None = None) -> None:
        if not bucket:
            raise S3Error("S3_BUCKET이 설정되지 않았습니다 (simulator/.env).")
        self._bucket = bucket
        self._client = client or boto3.client(
            "s3",
            region_name=region or None,
            config=BotoConfig(
                connect_timeout=params.S3_TIMEOUT_SECONDS,
                read_timeout=params.S3_TIMEOUT_SECONDS,
                retries={"max_attempts": 3},
            ),
        )

    def check_access(self) -> None:
        """버킷이 있고 bronze/ 경로를 조회할 수 있는지 확인한다."""
        try:
            self._client.list_objects_v2(
                Bucket=self._bucket, Prefix=f"{params.PATH_PREFIX}/", MaxKeys=1
            )
        except (BotoCoreError, ClientError) as error:
            raise S3Error(describe_error(error)) from None

    def list_objects(self, prefix: str) -> Iterator[S3Object]:
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            try:
                page = self._client.list_objects_v2(**kwargs)
            except (BotoCoreError, ClientError) as error:
                raise S3Error(describe_error(error)) from None
            for item in page.get("Contents", []):
                yield S3Object(str(item["Key"]), int(item["Size"]), item["LastModified"])
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")

    def iter_lines(self, key: str) -> Iterator[bytes]:
        """객체를 한 줄씩 넘겨 준다. 파일로 저장하지 않는다. 줄 끝 개행은 떼고, 빈 줄도 그대로 준다."""
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
            for line in body.iter_lines(keepends=False):
                yield bytes(line)
        except (BotoCoreError, ClientError) as error:
            raise S3Error(describe_error(error)) from None

    def public_access_block(self) -> str:
        """공개 차단 설정 요약. 조회 권한이 없으면 '확인 못 함'."""
        try:
            config = self._client.get_public_access_block(Bucket=self._bucket)[
                "PublicAccessBlockConfiguration"
            ]
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code == "NoSuchPublicAccessBlockConfiguration":
                return "공개 차단 설정 없음"
            return "확인 못 함"
        except BotoCoreError:
            return "확인 못 함"
        return "공개 차단 모두 켜짐" if all(config.values()) else "공개 차단 일부만 켜짐"
