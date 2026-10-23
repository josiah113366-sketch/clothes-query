"""spark-submit 반환 코드와 Driver Pod의 최종 상태를 함께 검증한다."""
from __future__ import annotations

import argparse
import json
import re
import signal
import ssl
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

import yaml

TAINT = {"key": "clothes-query/dedicated", "operator": "Equal", "value": "spark", "effect": "NoSchedule"}


class SubmissionError(RuntimeError):
    pass


def check_templates(directory):
    for role in ("driver", "executor"):
        template = yaml.safe_load((Path(directory) / (role + "-pod-template.yaml")).read_text())
        spec = template.get("spec", {}) if isinstance(template, dict) else {}
        if not any(all(item.get(k) == v for k, v in TAINT.items())
                   for item in spec.get("tolerations", []) if isinstance(item, dict)):
            raise SubmissionError(role + " template에 Spark 전용 노드 toleration이 없습니다")
        if not any(c.get("name") == "spark-main" for c in spec.get("containers", [])):
            raise SubmissionError(role + " template에 spark-main 컨테이너가 없습니다")


class PodClient:
    def __init__(self, namespace, name):
        self.path = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.context = ssl.create_default_context(cafile=str(self.path / "ca.crt"))
        self.url = ("https://kubernetes.default.svc/api/v1/namespaces/"
                    + quote(namespace, safe="") + "/pods/" + quote(name, safe=""))

    def request(self, method="GET", body=None):
        # 매 요청에서 회전된 토큰을 읽으며 API 응답·토큰을 로그에 출력하지 않는다.
        token = (self.path / "token").read_text().strip()
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(self.url, data=data, headers=headers, method=method),
                         context=self.context, timeout=10) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except HTTPError as error:
            if error.code == 404:
                return None
            raise SubmissionError(f"Driver Pod API {method} 실패: HTTP {error.code}") from None
        except (URLError, TimeoutError, ValueError):
            raise SubmissionError("Driver Pod API 통신/응답 확인 실패") from None

    def read(self):
        return self.request()



def driver_finished(pod, container_name="spark-main"):
    status = pod.get("status", {})
    phase = status.get("phase")
    states = status.get("containerStatuses", [])
    main = next((item for item in states if item.get("name") == container_name), {})
    ended = main.get("state", {}).get("terminated")
    if ended is not None and (ended.get("exitCode") != 0 or ended.get("signal", 0) != 0):
        raise SubmissionError(f"Driver 종료 실패: phase={phase}, exit_code={ended.get('exitCode')}")
    if phase == "Failed":
        raise SubmissionError(f"Driver Pod 실패: phase=Failed, exit_code={None if ended is None else ended.get('exitCode')}")
    if phase == "Succeeded":
        if ended is None or type(ended.get("exitCode")) is not int or ended["exitCode"] != 0:
            raise SubmissionError("Driver Succeeded의 주 컨테이너 종료 코드 0을 확인하지 못했습니다")
        return True
    if phase not in {None, "Pending", "Running"}:
        raise SubmissionError("Driver Pod 상태를 확정할 수 없습니다")
    return False


def monitor(process, client, timeout, *, sleep=time.sleep, clock=time.monotonic):
    deadline, observed, success = clock() + timeout, None, False
    last_pod = None
    try:
        while clock() < deadline:
            last_pod = client.read()
            if last_pod is None:
                if observed is not None:
                    raise SubmissionError("종료 확인 전에 Driver Pod가 사라졌습니다")
            else:
                uid = last_pod.get("metadata", {}).get("uid")
                if not uid or (observed is not None and uid != observed):
                    raise SubmissionError("Driver Pod UID를 확인할 수 없거나 변경됐습니다")
                observed = uid
                finished = driver_finished(last_pod)
                if finished and process.poll() == 0:
                    success = True
                    print("Driver phase=Succeeded, exit_code=0, spark_submit_exit_code=0", flush=True)
                    return
            code = process.poll()
            if code is not None and code != 0:
                raise SubmissionError(f"spark-submit 실패: exit_code={code}")
            sleep(2)
        raise SubmissionError("Driver 최종 상태 확인 시간 초과")
    finally:
        if not success and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--template-dir", default="/opt/spark/infra")
    parser.add_argument("--timeout-seconds", type=int, default=3000)
    parser.add_argument("spark_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", args.namespace):
        parser.error("유효한 namespace가 필요합니다")
    if not 1 <= args.timeout_seconds <= 3300:
        parser.error("timeout-seconds는 1~3300이어야 합니다")
    arguments = args.spark_arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if not arguments:
        parser.error("spark-submit 인자가 필요합니다")
    if any(arg.startswith("spark.kubernetes.driver.pod.name=") for arg in arguments):
        parser.error("Driver Pod 이름은 제출 래퍼가 지정합니다")

    def interrupted(_number, _frame):
        raise SubmissionError("제출 작업이 중단됐습니다")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    name = "silver-gold-a-" + uuid4().hex[:24] + "-driver"
    try:
        check_templates(args.template_dir)
        client = PodClient(args.namespace, name)
        print("Driver Pod: " + args.namespace + "/" + name, flush=True)
        process = subprocess.Popen(["/opt/spark/bin/spark-submit", "--conf",
                                    "spark.kubernetes.driver.pod.name=" + name, *arguments])
        monitor(process, client, args.timeout_seconds)
    except (SubmissionError, OSError) as error:
        message = str(error) if isinstance(error, SubmissionError) else "제출기 파일/프로세스 설정 오류"
        print(message, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
