FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_DEFAULT_REGION=ap-northeast-1
WORKDIR /app
COPY pipelines/requirements.txt /app/pipelines/requirements.txt
RUN pip install --no-cache-dir -r pipelines/requirements.txt \
    && useradd --uid 10001 --create-home batch
COPY pipelines/ /app/pipelines/
COPY docs/contracts/format_rules.yaml /app/docs/contracts/format_rules.yaml
ARG CODE_REF=unknown
ENV PIPELINE_CODE_REF=$CODE_REF
RUN test -n "$CODE_REF" && test "$CODE_REF" != unknown
USER 10001
ENTRYPOINT ["python", "-m", "pipelines.batch"]
