#!/bin/sh
# ECS 태스크 진입점 (2026-10-18 sim/review-ecs). 로컬과 같은 rsim 명령만 부른다(기능 차이 없음).
#
#   인자 없음 : 하루치 실행. ORDERS_SOURCE 로 주문 입력을 고른다
#               fake(기본) : 가짜 주문 만들기(rsim orders-fake) → 그날 리뷰 만들기(rsim run --source orders --sink lake)
#               rds        : RDS orders 테이블을 읽어 그날 리뷰 만들기(rsim run --source rds --sink lake, 2026-10-21)
#   인자 있음 : 그대로 rsim 에 넘긴다. 예) inject --file s3://.../manual/a.csv  (deploy/run_inject.py 가 이렇게 부른다)
#
# 환경변수 (태스크 정의에 deploy.py·switch.py 가 넣는다. 한 번만 바꾸려면 RunTask overrides)
#   RUN_DATE           리뷰 날짜(UTC, YYYY-MM-DD). 비우면 어제(UTC) = 로컬 rsim run 기본값과 같다
#   ORDERS_SOURCE      fake(기본) / rds. rds 면 ORDERS_DATABASE_URL 이 secret 으로 들어온다(deploy/aws_common.secrets_of)
#   ORDERS_FAKE_START  가짜 주문 시작 시각. 고정값이라 같은 날짜를 다시 돌려도 같은 주문 → 같은 리뷰 ID (덮어쓰기)
#   ORDERS_PER_DAY     하루 평균 주문 수. 하루 리뷰 수 ≈ ORDERS_PER_DAY x REVIEW_RATE
#   ORDERS_SEED        가짜 주문 난수 시드
#   LLM                bedrock(기본) / fake(비용 0원, 배관 확인용)
# ORDERS_SOURCE=rds 면 가짜 주문 단계가 빠진다. 아래 fake 부분은 ORDERS_*(가짜 주문) 값만 쓴다.
set -eu

if [ "$#" -gt 0 ]; then
    exec rsim "$@"
fi

DAY="${RUN_DATE:-$(date -u -d yesterday +%F)}"

if [ "${ORDERS_SOURCE:-fake}" = "rds" ]; then
    echo "리뷰 날짜 $DAY (UTC), 주문 = RDS orders 테이블, LLM=${LLM:-bedrock}"
    exec rsim run --source rds --sink lake --llm "${LLM:-bedrock}" --date "$DAY"
fi

START="${ORDERS_FAKE_START:-2026-10-01T00:00:00+00:00}"
# 시작일부터 DAY 까지 날짜 수 (DAY 당일 포함). 리뷰는 결제 0~7일 뒤라 DAY 당일까지의 주문이 쓰인다
DAYS=$(python -c "import datetime as d,sys; s=d.datetime.fromisoformat(sys.argv[1]).date(); print((d.date.fromisoformat(sys.argv[2])-s).days+1)" "$START" "$DAY")
if [ "$DAYS" -lt 1 ]; then
    echo "RUN_DATE($DAY) 가 ORDERS_FAKE_START($START) 보다 앞입니다" >&2
    exit 2
fi

echo "리뷰 날짜 $DAY (UTC), 가짜 주문 $START 부터 ${DAYS}일, 하루 ${ORDERS_PER_DAY:-1000}건, LLM=${LLM:-bedrock}"
rsim orders-fake --start "$START" --days "$DAYS" --per-day "${ORDERS_PER_DAY:-1000}" --seed "${ORDERS_SEED:-42}"
exec rsim run --source orders --sink lake --llm "${LLM:-bedrock}" --date "$DAY"
