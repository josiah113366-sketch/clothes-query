"""Gold B 이미지(Dockerfile) 시험. 빌드하지 않고 넣을 파일 목록과 Dockerfile의 약속을 확인한다.

넣을 파일은 Dockerfile.dockerignore가 정한다. 여기서는 Docker(moby patternmatcher)와 같은 규칙으로 저장소 파일을 걸러,
잡 4개가 부르는 모듈(공통 모듈 포함)과 형식 규칙표가 모두 들어가고 시험·문서·로컬 파일은 빠지는지 본다.
실제 빌드와 이미지 안 import는 팀 기본 Spark 이미지로 빌드할 때 Dockerfile이 확인한다.
"""
from __future__ import annotations

import ast
from pathlib import Path
import posixpath
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
GOLD_B = ROOT / "pipelines" / "gold_b"
DOCKERFILE = GOLD_B / "Dockerfile"
IGNORE = GOLD_B / "Dockerfile.dockerignore"
# 잡 4개의 입구 (Dockerfile이 빌드할 때 import로도 확인한다)
ENTRY_MODULES = ("pipelines.gold_b.jobs.streaming_ingest", "pipelines.gold_b.jobs.reprocess",
                 "pipelines.gold_b.jobs.compact", "pipelines.gold_b.collector.bronze_lag_collector")


# ---------- Docker의 .dockerignore 규칙 (moby patternmatcher와 같게) ----------

def _regex(pattern: str) -> re.Pattern:
    """**는 폴더를 넘어 아무거나, *는 / 빼고 아무거나, ?는 / 빼고 한 글자."""
    out, i = "^", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*" and pattern[i + 1:i + 2] == "*":
            i += 1
            if pattern[i + 1:i + 2] == "/":
                i += 1
            out += ".*" if i + 1 >= len(pattern) else "(.*/)?"
        elif ch == "*":
            out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        else:
            out += re.escape(ch)
        i += 1
    return re.compile(out + "$")


def ignore_patterns(text: str) -> list[tuple[bool, re.Pattern]]:
    """(다시 넣는 규칙인가, 정규식). 빈 줄과 # 줄은 건너뛴다."""
    patterns = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        include = line.startswith("!")
        pattern = posixpath.normpath(line[1:].strip() if include else line).lstrip("/")
        patterns.append((include, _regex(pattern)))
    return patterns


def excluded(path: str, patterns: list[tuple[bool, re.Pattern]]) -> bool:
    """빌드에서 빠지는가. 규칙을 차례로 보고 마지막에 맞은 규칙을 따른다. 폴더가 맞으면 그 아래 파일도 맞은 것으로 본다."""
    matched = False
    parents = path.split("/")[:-1]
    for include, regex in patterns:
        if include != matched:   # 이미 들어간 파일에 다시 넣는 규칙, 이미 빠진 파일에 빼는 규칙은 볼 필요 없음
            continue
        if regex.match(path) or any(regex.match("/".join(parents[:i + 1])) for i in range(len(parents))):
            matched = not include
    return matched


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git ls-files를 쓸 수 없음")
    return out.splitlines()


@pytest.fixture(scope="module")
def included(tracked) -> set[str]:
    patterns = ignore_patterns(IGNORE.read_text(encoding="utf-8"))
    return {path for path in tracked if not excluded(path, patterns)}


def test_matcher_follows_docker_rules():
    patterns = ignore_patterns("**\n!src/*.py\n!keep/\n**/test_*.py\n")
    assert not excluded("src/a.py", patterns)
    assert excluded("src/b/a.py", patterns)            # *는 폴더를 넘지 않는다
    assert excluded("src/test_a.py", patterns)         # 뒤의 규칙이 다시 뺀다
    assert not excluded("keep/deep/x.md", patterns)    # 폴더를 다시 넣으면 그 아래가 모두 들어간다
    assert excluded("other/a.py", patterns)


# ---------- 넣을 파일 ----------

def _module_file(module: str, files: set[str]) -> str | None:
    base = module.replace(".", "/")
    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        if candidate in files:
            return candidate
    return None


def _pipelines_imports(source: str) -> set[str]:
    """pipelines.로 시작하는 import (from pipelines.x import y는 y가 모듈일 수도 있어 둘 다)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names if alias.name.startswith("pipelines."))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("pipelines."):
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_jobs_and_everything_they_import_are_in_the_image(tracked, included):
    files = set(tracked)
    todo, needed = list(ENTRY_MODULES), set()
    while todo:
        path = _module_file(todo.pop(), files)
        if path is None or path in needed:
            continue
        needed.add(path)
        todo.extend(_pipelines_imports((ROOT / path).read_text(encoding="utf-8")))
    assert {"pipelines/format_rules.py", "pipelines/payment_fingerprint.py", "pipelines/timestamps.py",
            "pipelines/gold_b/ledger.py", "pipelines/gold_b/format_check.py"} <= needed
    assert needed <= included, sorted(needed - included)
    # 코드 밖에서 읽는 파일: 형식 규칙표, 적재 잡 설정, 패키지 목록
    assert {"docs/contracts/format_rules.yaml", "pipelines/gold_b/config/gold_b.yaml",
            "pipelines/gold_b/requirements.txt"} <= included


def test_only_code_and_settings_go_in(included):
    """시험·문서·Athena SQL·Silver·Gold A 코드는 넣지 않는다."""
    allowed = re.compile(r"^(pipelines/[^/]+\.py|pipelines/gold_b/([^/]+\.py|requirements\.txt|config/gold_b\.yaml|"
                         r"jobs/[^/]+\.py|collector/[^/]+\.py)|docs/contracts/format_rules\.yaml)$")
    assert included and all(allowed.match(path) for path in included), sorted(p for p in included if not allowed.match(p))
    assert not any(posixpath.basename(path).startswith("test_") for path in included)


@pytest.mark.parametrize("path", [
    ".env", "pipelines/.env", ".local/pt/x.py", "pipelines/gold_b/.venv/lib/site.py",
    "pipelines/gold_b/__pycache__/ledger.cpython-310.pyc", "pipelines/gold_b/jobs/__pycache__/reprocess.cpython-310.pyc",
    "pipelines/gold_b/tests/test_ingest.py", "pipelines/test_transactions_flow.py", "pipelines/silver/transactions.py",
    "pipelines/gold_b/ddl/payment_events.sql", "pipelines/gold_b/README.md", ".worktrees/t-coll/pipelines/timestamps.py",
])
def test_local_and_test_files_stay_out(path):
    """저장소에 없는 로컬 파일(가상환경, 캐시, 비밀 값, 작업 폴더)도 빌드에 들어가지 않는다."""
    assert excluded(path, ignore_patterns(IGNORE.read_text(encoding="utf-8")))


# ---------- Dockerfile의 약속 ----------

def dockerfile_lines() -> list[str]:
    return [line.strip() for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_starts_from_the_team_spark_image_without_a_default():
    """팀 기본 이미지 digest를 반드시 받고, Kafka 연결·S3A jar가 없는 이미지면 빌드를 멈춘다."""
    lines = dockerfile_lines()
    assert lines[:2] == ["ARG SPARK_IMAGE", "FROM ${SPARK_IMAGE}"]
    text = DOCKERFILE.read_text(encoding="utf-8")
    for jar in ("spark-sql-kafka-0-10_2.13-", "kafka-clients-", "hadoop-aws-"):
        assert f"/opt/spark/jars/{jar}" in text, jar
    assert "sys.version_info[:2] == (3, 10)" in text


def test_code_location_entry_and_user():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "PYTHONPATH=/opt/gold_b" in text and "COPY pipelines/ /opt/gold_b/pipelines/" in text
    assert "COPY docs/contracts/format_rules.yaml /opt/gold_b/docs/contracts/format_rules.yaml" in text
    assert "python3 -m pip install --no-cache-dir -r pipelines/gold_b/requirements.txt" in text
    assert 'test "$CODE_REF" != unknown' in text   # 머지된 main 커밋으로만 만든다
    for module in (*ENTRY_MODULES, "pipelines.gold_b.format_check"):
        assert module in text, module                # 빌드할 때 import로 확인
    lines = dockerfile_lines()
    assert lines[-2:] == ["USER 185:0", 'ENTRYPOINT ["/opt/entrypoint.sh"]']
    # 적재 잡 제출 위치 (spark-submit local:///opt/gold_b/pipelines/gold_b/jobs/streaming_ingest.py)
    assert (GOLD_B / "jobs" / "streaming_ingest.py").is_file()
