# 대시보드 컨테이너 이미지. 빌드 컨텍스트는 앱 소스 폴더(dashboard/)다. repo 루트에서 실행:
#   docker build -f infra/platform/dashboard/Dockerfile -t dashboard:dev dashboard/
# 제외 목록은 이 파일 옆의 Dockerfile.dockerignore (BuildKit)가 적용된다.
FROM python:3.12-slim

# .pyc 파일을 만들지 않고, 로그를 바로 출력하게 한다.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성을 먼저 설치해야 코드만 바뀔 때 빌드 캐시가 재사용된다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# root가 아닌 고정 UID로 실행 (k8s runAsNonRoot 는 숫자 UID가 필요하다)
RUN useradd -m -u 10001 app && chown -R app /app
USER 10001

EXPOSE 8501

# 컨테이너 상태 확인용 Streamlit 내장 엔드포인트 (k8s probe와 같은 경로)
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')"

# address=0.0.0.0: 컨테이너 밖(Service)에서 접속하려면 필요.
# headless: 브라우저 자동 실행 끔. usageStats 끔: 외부 전송 방지.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
