# 리뷰 시뮬레이터 컨테이너 이미지
# - 로컬: docker compose --profile sim up --build simulator  (docker-compose.yml 참고)
# - AWS : 이 이미지를 ECR 에 올리고 ECS Fargate 태스크로 실행
#
# 이미지에는 코드 + .local/seeds.jsonl(말투 예시) + data/ 만 들어간다. 먼저 `rsim seeds` 로 시드를 만들어 둘 것.
# 시드에는 AI Hub 원문이 있어서 이미지를 공개 레지스트리에 올리지 않는다.
# .env 는 이미지에 넣지 않는다(.dockerignore). 설정은 실행할 때 환경변수로 준다.
FROM python:3.12-slim

# 파이썬 출력이 버퍼링 없이 바로 로그로 나오게 (docker logs / CloudWatch 에서 실시간 확인)
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY data ./data
COPY .local/seeds.jsonl ./.local/seeds.jsonl

# 기본 실행: Bedrock 으로 생성해서 Kafka 로 계속 전송 (초당 최대 0.5건)
# 옵션을 바꾸려면 compose 의 command 나 ECS 태스크 정의의 command 를 덮어쓴다
ENTRYPOINT ["rsim"]
CMD ["run", "--sink", "kafka", "--count", "0", "--max-rps", "0.5"]
