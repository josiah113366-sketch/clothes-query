"""베이스라인 적재: 생성 → COPY → 커밋. 회원 값은 출력하지도 파일로 쓰지도 않는다."""

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psycopg

from sim.common.db import safe_db_errors
from sim.common.regions import RegionTable
from sim.common.rng import SimRandom
from sim.member import params
from sim.member.generate import allocate_phones, generate_member, random_signup_at
from sim.member.model import NewMember

COLUMNS: tuple[str, ...] = (
    "member_id",
    "name",
    "email",
    "phone",
    "birth_date",
    "password_hash",
    "gender",
    "signup_at",
    "signup_channel",
    "marketing_consent",
    "status",
    "withdrawn_at",
    "region_sigungu",
    "age_band",
)
COPY_SQL = f"COPY members ({', '.join(COLUMNS)}) FROM STDIN"


class TableNotEmptyError(RuntimeError):
    pass


def iter_members(rng: SimRandom, count: int, regions: RegionTable) -> Iterator[NewMember]:
    """회원을 앞에서부터 하나씩 만든다. 난수 소비 순서는 배치 크기와 무관하다."""
    phones = allocate_phones(rng, count)
    for phone in phones:
        yield generate_member(rng, random_signup_at(rng), regions, phone)


def _row_values(member: NewMember) -> tuple[object, ...]:
    return tuple(getattr(member, column) for column in COLUMNS)


def _hash_line(member: NewMember) -> bytes:
    fields = []
    for value in _row_values(member):
        if value is None:
            fields.append("")
        elif isinstance(value, bool):
            fields.append("t" if value else "f")
        elif hasattr(value, "isoformat"):
            fields.append(value.isoformat())
        else:
            fields.append(str(value))
    return ("|".join(fields) + "\n").encode()


@dataclass
class RunSummary:
    """PII 없는 집계값만 담는다."""

    mode: str
    count: int
    seed: int
    batch_size: int
    region_file: str
    region_rows: int
    signup_from: str
    signup_to: str
    elapsed_seconds: float = 0.0
    by_age_band: dict[str, int] = field(default_factory=dict)
    by_gender: dict[str, int] = field(default_factory=dict)
    by_channel: dict[str, int] = field(default_factory=dict)
    repro_hash: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def lines(self) -> list[str]:
        def counts(data: dict[str, int]) -> str:
            return ", ".join(f"{k}={v:,}" for k, v in sorted(data.items()))

        return [
            f"모드: {self.mode}",
            f"인원: {self.count:,}  시드: {self.seed}  배치 크기: {self.batch_size:,}",
            f"지역 파일: {self.region_file} ({self.region_rows}행)",
            f"가입 기간: {self.signup_from} ~ {self.signup_to} (미만)",
            f"소요 시간: {self.elapsed_seconds:.1f}초",
            f"나이대: {counts(self.by_age_band)}",
            f"성별: {counts(self.by_gender)}",
            f"채널: {counts(self.by_channel)}",
            f"재현성 해시: {self.repro_hash}",
        ]


def table_is_empty(conn: psycopg.Connection) -> bool:
    with safe_db_errors():
        row = conn.execute("SELECT EXISTS (SELECT 1 FROM members)").fetchone()
    return not (row and row[0])


def run_baseline(
    regions: RegionTable,
    count: int,
    seed: int,
    batch_size: int,
    conn: psycopg.Connection | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> RunSummary:
    """conn이 None이면 생성만 한다 (--dry-run). 아니면 배치마다 COPY하고 커밋한다."""
    if conn is not None and not table_is_empty(conn):
        raise TableNotEmptyError(
            "members 테이블이 비어 있지 않아 아무것도 넣지 않았습니다. "
            "로컬이면 `docker compose down -v` 후 다시 실행하세요."
        )

    started = time.monotonic()
    rng = SimRandom(seed)
    digest = hashlib.sha256()
    ages: Counter[str] = Counter()
    genders: Counter[str] = Counter()
    channels: Counter[str] = Counter()
    batch: list[NewMember] = []

    def flush() -> None:
        if conn is None or not batch:
            return
        with safe_db_errors():
            try:
                with conn.cursor() as cur, cur.copy(COPY_SQL) as copy:
                    for member in batch:
                        copy.write_row(_row_values(member))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    for done, member in enumerate(iter_members(rng, count, regions), start=1):
        digest.update(_hash_line(member))
        ages[member.age_band] += 1
        genders[member.gender] += 1
        channels[member.signup_channel] += 1
        batch.append(member)
        if len(batch) >= batch_size:
            flush()
            batch.clear()
        if progress and done % params.PROGRESS_EVERY == 0:
            progress(done, count)
    flush()
    batch.clear()

    return RunSummary(
        mode="dry-run" if conn is None else "load",
        count=count,
        seed=seed,
        batch_size=batch_size,
        region_file=regions.source_name,
        region_rows=len(regions),
        signup_from=params.SIGNUP_START.isoformat(),
        signup_to=params.SIGNUP_END.isoformat(),
        elapsed_seconds=round(time.monotonic() - started, 2),
        by_age_band={band: ages[band] for band in params.AGE_BANDS},
        by_gender=dict(genders),
        by_channel=dict(channels),
        repro_hash=digest.hexdigest()[:12],
    )


def write_summary(summary: RunSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary.to_json() + "\n", encoding="utf-8")
