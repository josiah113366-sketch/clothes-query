# 시뮬레이터 이미지. 하나의 이미지를 명령만 바꿔 쓴다(ECS 태스크의 controller·member·behavior 컨테이너).
# 비밀값은 넣지 않는다(API 주소·DB 접속 문자열은 ECS 환경 변수·Secret으로 받는다).
# python:3.12-slim (2026-10-20 digest, api/Dockerfile 과 같다)
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --no-create-home sim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY data ./data
RUN pip install . && rm -rf /root/.cache

# 컨트롤러 데이터 오염의 RDS 접속(sslmode=verify-full)용 CA 묶음 (공개 인증서, 2026-10-21 받은 값의 sha256)
ADD --checksum=sha256:d1df75221341812a657d7c7b070ff61ce78824fbf05acf499f7e394f5ff58d50 \
    https://truststore.pki.rds.amazonaws.com/ap-northeast-1/ap-northeast-1-bundle.pem /etc/ssl/rds/ap-northeast-1-bundle.pem
RUN chmod 0644 /etc/ssl/rds/ap-northeast-1-bundle.pem

# 제어 파일 폴더. ECS 태스크는 여기에 공유 볼륨을 붙인다.
# Fargate 는 이미지의 VOLUME 경로 소유자를 볼륨에 이어받으므로, 비root(sim)가 control.json 을 쓸 수 있다.
RUN mkdir -p /control && chown sim:sim /control
VOLUME ["/control"]

USER 10001
ENTRYPOINT ["sim"]
