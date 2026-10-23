FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app AWS_EC2_METADATA_DISABLED=true
WORKDIR /app
COPY pipelines/gold_b/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && pip check && pip freeze > /app/requirements.lock.txt \
    && groupadd --gid 10001 collector \
    && useradd --uid 10001 --gid 10001 --no-create-home collector
COPY pipelines/gold_b/__init__.py /app/pipelines/gold_b/__init__.py
COPY pipelines/gold_b/collector/*.py /app/pipelines/gold_b/collector/
USER 10001:10001
ENTRYPOINT ["python", "-m", "pipelines.gold_b.collector.bronze_lag_collector"]
CMD ["--interval", "60"]
