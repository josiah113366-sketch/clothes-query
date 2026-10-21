# 업무 API 이미지. 비밀값은 넣지 않는다(DB·Kafka 인증서는 K8s Secret으로 붙인다).
# python:3.12-slim (2026-10-20 digest)
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --no-create-home api
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . && rm -rf /root/.cache

USER 10001
EXPOSE 8000
# 접근 로그는 앱이 JSON으로 남긴다(uvicorn 기본 접근 로그는 쿼리 문자열을 그대로 찍는다)
CMD ["uvicorn", "clothes_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
