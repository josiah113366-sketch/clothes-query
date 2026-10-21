# 판정 잡 이미지 (제안). 빌드 위치는 agent/detect 폴더: docker build -t <이름> agent/detect
# 이미지 저장소(ECR) 등록과 Airflow DAG 연결은 인프라 담당과 정한다.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rules.py job.py athena_io.py run_job.py ./
RUN useradd --system --no-create-home runner
USER runner
ENTRYPOINT ["python", "run_job.py"]
