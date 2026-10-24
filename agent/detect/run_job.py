"""판정 잡 실행 진입점: Airflow가 5분마다 이 파일을 한 번 실행한다 (컨테이너 이미지의 ENTRYPOINT).

환경 변수 (비밀값은 없다. AWS 권한은 ServiceAccount에 연결된 역할이 준다)
  ATHENA_WORKGROUP   (필수) 판정용 workgroup 이름
  ATHENA_DATABASE    기본 gold_b
  AWS_REGION         기본은 boto3가 정한다(ap-northeast-1)
  JUDGE_TICK         선택. 순찰 시각(UTC, 예: 2026-10-21T15:10:00). Airflow가 논리 시각(data_interval_end)을 넘기면
                     실패한 작업을 몇 분 뒤 다시 돌려도 같은 순찰 번호가 되어 이상 줄이 이중 저장되지 않는다
실행 결과 요약을 JSON 한 줄로 출력한다. 쿼리 결과나 쿼리 문장은 출력하지 않는다.
"""
import json
import os
import sys
from datetime import datetime, timezone

from athena_io import AthenaIO
from job import run_once
from rules import Config


def config_from_env(env):
    """환경 변수로 바꿀 수 있는 설정. SILVER_CHECKS_TABLE이 비어 있으면 R6은 돌지 않는다(기본)."""
    extra = {}
    if env.get("SILVER_CHECKS_TABLE"):
        extra["silver_checks_table"] = env["SILVER_CHECKS_TABLE"]
    if env.get("R6_CHECK_NAME"):
        extra["r6_check_name"] = env["R6_CHECK_NAME"]
    return Config(dialect="athena", **extra)


def main(env=None, io=None, now=None):
    env = os.environ if env is None else env
    workgroup = env.get("ATHENA_WORKGROUP")
    if io is None:
        if not workgroup:
            sys.exit("ATHENA_WORKGROUP 환경 변수가 필요합니다.")
        io = AthenaIO(workgroup, env.get("ATHENA_DATABASE", "gold_b"), region=env.get("AWS_REGION"))
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    tick = env.get("JUDGE_TICK")
    if tick:
        tick = datetime.fromisoformat(tick.replace("Z", "+00:00"))
        tick = tick.astimezone(timezone.utc).replace(tzinfo=None) if tick.tzinfo else tick
    summary = run_once(io.query, io.write, config_from_env(env), now, tick or None)
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return summary


if __name__ == "__main__":
    main()
