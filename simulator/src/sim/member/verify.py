"""적재 결과 확인 (읽기 전용). SQL 집계만 읽고 PII는 읽지도 출력하지도 않는다."""

from dataclasses import dataclass
from datetime import timedelta
from math import sqrt

import psycopg

from sim.common.db import safe_db_errors
from sim.common.regions import RegionTable
from sim.member import params
from sim.member.generate import age_band_of

KST_SQL = "signup_at AT TIME ZONE 'Asia/Seoul'"


@dataclass(frozen=True)
class CheckResult:
    number: int
    name: str
    passed: bool
    detail: str


def _within(count: int, total: int, p: float) -> bool:
    """count/total이 p ± SIGMA_LIMIT·σ 안인가 (σ = √(p(1−p)/N))."""
    sigma = sqrt(p * (1 - p) / total)
    return abs(count / total - p) <= params.SIGMA_LIMIT * sigma


def _ratio_check(number: int, name: str, observed: dict[str, int], expected: dict[str, float]):
    total = sum(observed.values())
    bad = [
        key
        for key, p in expected.items()
        if total == 0 or not _within(observed.get(key, 0), total, p)
    ]
    detail = "모두 범위 안" if not bad else f"범위 밖: {', '.join(bad)}"
    return CheckResult(number, name, not bad, detail)


def _scalar(conn: psycopg.Connection, query: str, args: tuple = ()) -> int:
    row = conn.execute(query, args).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _grouped(conn: psycopg.Connection, query: str, args: tuple = ()) -> dict[str, int]:
    return {str(k): int(v) for k, v in conn.execute(query, args).fetchall()}


def run_verify(conn: psycopg.Connection, regions: RegionTable, expected: int) -> list[CheckResult]:
    results: list[CheckResult] = []
    with safe_db_errors():
        total = _scalar(conn, "SELECT count(*) FROM member")
        results.append(CheckResult(1, "행 수", total == expected, f"{total:,} / 기대 {expected:,}"))
        if total == 0:
            return results

        dup_email = _scalar(conn, "SELECT count(*) - count(DISTINCT email) FROM member")
        dup_phone = _scalar(conn, "SELECT count(*) - count(DISTINCT phone) FROM member")
        results.append(
            CheckResult(
                2,
                "이메일·전화 중복",
                dup_email == 0 and dup_phone == 0,
                f"이메일 {dup_email}건, 전화 {dup_phone}건",
            )
        )

        nulls = _scalar(
            conn,
            "SELECT count(*) FROM member WHERE name IS NULL OR email IS NULL OR phone IS NULL"
            " OR birth_date IS NULL OR password_hash IS NULL",
        )
        results.append(CheckResult(3, "필수 PII 채워짐", nulls == 0, f"NULL 행 {nulls}건"))

        bad_status = _scalar(
            conn,
            "SELECT count(*) FROM member WHERE status <> 'ACTIVE' OR withdrawn_at IS NOT NULL",
        )
        results.append(
            CheckResult(4, "상태", bad_status == 0, f"ACTIVE 아님/탈퇴 시각 있음 {bad_status}건")
        )

        out_of_range = _scalar(
            conn,
            "SELECT count(*) FROM member WHERE signup_at < %s OR signup_at >= %s",
            (params.SIGNUP_START, params.SIGNUP_END),
        )
        results.append(
            CheckResult(5, "signup_at 범위", out_of_range == 0, f"범위 밖 {out_of_range}건")
        )

        daily = _grouped(conn, f"SELECT ({KST_SQL})::date, count(*) FROM member GROUP BY 1")
        p_day = 1 / params.SIGNUP_DAYS
        sigma_day = sqrt(total * p_day * (1 - p_day))
        bad_days = sum(
            1
            for day in range(params.SIGNUP_DAYS)
            if abs(_day_count(daily, day) - total * p_day) > params.SIGMA_LIMIT * sigma_day
        )
        extra_days = len(daily) - sum(1 for d in range(params.SIGNUP_DAYS) if _day_count(daily, d))
        results.append(
            CheckResult(
                6,
                "일별 가입 수",
                bad_days == 0 and extra_days == 0,
                f"범위 밖 {bad_days}일 (기대 {total * p_day:.1f} ± {params.SIGMA_LIMIT * sigma_day:.1f})",
            )
        )

        hourly = _grouped(
            conn, f"SELECT extract(hour FROM {KST_SQL})::int, count(*) FROM member GROUP BY 1"
        )
        results.append(
            _ratio_check(7, "시간대별 비율", hourly, {str(h): 1 / 24 for h in range(24)})
        )

        weights = params.AGE_BAND_WEIGHTS
        weight_total = sum(weights.values())
        results.append(
            _ratio_check(
                8,
                "나이대 비율",
                _grouped(conn, "SELECT age_band, count(*) FROM member GROUP BY 1"),
                {band: weights[band] / weight_total for band in params.AGE_BANDS},
            )
        )

        age_rows = conn.execute(
            "SELECT age_band,"
            f" extract(year FROM {KST_SQL})::int - extract(year FROM birth_date)::int AS age,"
            " count(*) FROM member GROUP BY 1, 2"
        ).fetchall()
        mismatched = 0
        min_age = min(int(age) for _, age, _ in age_rows)
        for band, age, n in age_rows:
            try:
                ok = age_band_of(int(age)) == band
            except ValueError:
                ok = False
            if not ok:
                mismatched += int(n)
        results.append(
            CheckResult(
                9,
                "age_band 정합성",
                mismatched == 0 and min_age >= params.MIN_AGE,
                f"불일치 {mismatched}건, 최소 나이 {min_age}",
            )
        )

        unknown_regions = _scalar(
            conn,
            "SELECT count(*) FROM member WHERE region_sigungu <> ALL(%s)",
            (list(regions.names),),
        )
        results.append(
            CheckResult(
                10, "지역", unknown_regions == 0, f"지역 파일에 없는 값 {unknown_regions}건"
            )
        )

        results.append(
            _ratio_check(
                11,
                "시도별 비율",
                _grouped(
                    conn,
                    "SELECT split_part(region_sigungu, ' ', 1), count(*) FROM member GROUP BY 1",
                ),
                regions.sido_weights(),
            )
        )

        flags = conn.execute(
            "SELECT count(*) FILTER (WHERE gender = 'F'),"
            " count(*) FILTER (WHERE signup_channel = 'app'),"
            " count(*) FILTER (WHERE marketing_consent) FROM member"
        ).fetchone()
        assert flags is not None
        female, app, consent = (int(v) for v in flags)
        bad = [
            label
            for label, count, p in (
                ("여성", female, params.FEMALE_RATIO),
                ("app", app, params.APP_CHANNEL_RATIO),
                ("마케팅 동의", consent, params.MARKETING_CONSENT_RATIO),
            )
            if not _within(count, total, p)
        ]
        results.append(
            CheckResult(
                12,
                "성별·채널·마케팅 동의 비율",
                not bad,
                f"여성 {female / total:.3f}, app {app / total:.3f}, 동의 {consent / total:.3f}"
                + (f" (범위 밖: {', '.join(bad)})" if bad else ""),
            )
        )
    return results


def _day_count(daily: dict[str, int], day_offset: int) -> int:
    day = (params.SIGNUP_START + timedelta(days=day_offset)).date()
    return daily.get(day.isoformat(), 0)
