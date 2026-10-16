"""테스트 공통 준비: 임시 폴더에 작은 시드 파일을 만들고 그 폴더에서 실행한다.

실제 .local/seeds.jsonl(AI Hub 원문)은 저장소에 없으므로, 테스트는 여기서 만든 가짜 시드만 쓴다.
Bedrock·Kafka 는 부르지 않는다(비용 0원).
"""

import json
from pathlib import Path

import pytest

SEED_ROWS = [
    {
        "source": "synth",
        "category": None,
        "product_name": None,
        "rating": None,
        "text": "배송 빨라요",
    },
    {
        "source": "aihub",
        "category": "여성의류",
        "product_name": "OO 니트",
        "rating": 5,
        "text": "핏 예뻐요",
    },
    {
        "source": "aihub",
        "category": "남성의류",
        "product_name": "OO 셔츠",
        "rating": 4,
        "text": "괜찮아요",
    },
    {
        "source": "aihub",
        "category": "패션슈즈",
        "product_name": "OO 운동화",
        "rating": 2,
        "text": "작아요",
    },
    {
        "source": "aihub",
        "category": "잡화",
        "product_name": "OO 가방",
        "rating": 5,
        "text": "튼튼해요",
    },
]


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """review-simulator/ 처럼 쓰는 임시 작업 폴더. 시드 파일과 고정 난수 시드를 준비한다."""
    local = tmp_path / ".local"
    local.mkdir()
    (local / "seeds.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in SEED_ROWS), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RANDOM_SEED", "7")
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    return tmp_path
