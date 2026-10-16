"""시드(말투 예시) 파일 만들기: .local/seeds.jsonl  (명령: rsim seeds)

Bedrock 프롬프트에 "이런 말투로 써 달라"는 예시로 넣을 리뷰들을 한 파일로 합친다.
시뮬레이터 실행 때마다 원본 폴더를 뒤지지 않도록 한 번만 돌려 두면 된다.
(Docker 이미지 / ECS 에는 이 결과 파일만 들어가면 된다.)

입력 3종
--------
1. synth      : 우리가 Gemini 로 만든 합성 리뷰
                review-analysis/voc_amazon_ko/absa_pilot/synth_ko.v1.json
2. aihub      : AI Hub 속성기반 감정분석 '쇼핑몰' 라벨링 데이터 (SNS 는 블로그 글이라 길어서 제외)
                review-analysis/aihub_dataset/*/02.라벨링데이터/*쇼핑몰*/*.json
3. handwritten: 실제 말투를 흉내 내 우리가 직접 쓴 리뷰
                review-simulator/.local/handwritten/*.csv  (형식은 data/handwritten/README.md)

출력 한 줄 형식 (JSON Lines)
---------------------------
{"source": "aihub", "category": "여성의류", "product_name": "OO 니트", "rating": 5,
 "text": "...", "aspects": [{"aspect": "사이즈·핏", "sentiment": "긍정"}]}

개인정보·내부자료 보호
----------------------
review-analysis/private/ 의 파일(실제 쇼핑몰 후기를 받아 적은 평가셋)은 Bedrock 같은 외부 서비스로
보내면 안 되는 자료라서, 경로에 'private' 가 들어간 파일은 어떤 옵션으로도 읽지 않는다.

실행 예
-------
rsim seeds                                               # 기본 경로(../../review-analysis) 사용
rsim seeds --analysis-dir D:/other/review-analysis --aihub-per-category 1500

결과 파일에는 AI Hub 원문(재배포 금지)과 직접 쓴 리뷰가 들어간다. 그래서 .local/ 에만 두고 커밋하지 않는다.
"""

from __future__ import annotations

import csv
import glob
import json
import random
from collections import Counter
from pathlib import Path

from rsim.review.taxonomy import AIHUB_ASPECT_MAP, AIHUB_POLARITY_MAP, ASPECTS, CATEGORIES


def _guard_private(path: Path) -> None:
    """내부 전용 자료(private 폴더)는 절대 시드로 쓰지 않는다."""
    if "private" in {p.lower() for p in path.parts}:
        raise SystemExit(f"[중단] 내부 전용 자료는 시드로 쓸 수 없습니다: {path}")


def _clean_aspects(raw: list[dict]) -> list[dict]:
    """속성 라벨을 10개 속성 기준으로 정리하고, 같은 속성이 여러 번 나오면 하나만 남긴다.

    라벨 가이드 R14/R20: 같은 속성에 서로 다른 감성이 섞이면 '중립'으로 합친다.
    """
    merged: dict[str, str] = {}
    for a in raw:
        name, senti = a.get("aspect"), a.get("sentiment")
        if name not in ASPECTS or senti not in ("긍정", "중립", "부정"):
            continue
        if name in merged and merged[name] != senti:
            merged[name] = "중립"
        else:
            merged[name] = senti
    return [{"aspect": k, "sentiment": v} for k, v in merged.items()]


# ---------------------------------------------------------------- 1. 합성 리뷰
def load_synth(analysis_dir: Path) -> list[dict]:
    path = analysis_dir / "voc_amazon_ko" / "absa_pilot" / "synth_ko.v1.json"
    _guard_private(path)
    if not path.exists():
        print(f"  - synth: 파일 없음, 건너뜀 ({path})")
        return []
    rows = []
    for r in json.loads(path.read_text(encoding="utf-8")):
        text = (r.get("review") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "source": "synth",
                # 합성 리뷰는 카테고리 정보가 없어서 '의류 공통'으로 둔다(어느 카테고리 예시로도 쓸 수 있음)
                "category": None,
                "product_name": None,
                "rating": None,
                "style": r.get("style"),
                "text": text,
                "aspects": _clean_aspects(r.get("aspects", [])),
            }
        )
    return rows


# ---------------------------------------------------------------- 2. AI Hub
def _score_to_rating(score: str | None) -> int | None:
    """AI Hub ReviewScore(0~100) → 별점 1~5. 100=5점, 80=4점, 60=3점, 40=2점, 20 이하=1점."""
    try:
        s = int(score)
    except (TypeError, ValueError):
        return None
    return max(1, min(5, round(s / 20)))


def load_aihub(
    analysis_dir: Path, per_category: int, max_len: int, rng: random.Random
) -> list[dict]:
    pattern = str(analysis_dir / "aihub_dataset" / "*" / "02.라벨링데이터" / "*쇼핑몰*" / "*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"  - aihub: 라벨링 JSON 없음, 건너뜀 ({pattern})")
        return []
    by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for f in files:
        _guard_private(Path(f))
        for r in json.loads(Path(f).read_text(encoding="utf-8-sig")):
            text = (r.get("RawText") or "").strip()
            cat = r.get("MainCategory")
            # 너무 긴 리뷰는 예시로 넣으면 토큰만 많이 먹어서 제외 (중앙값이 57자 정도)
            if not text or len(text) > max_len or cat not in by_cat:
                continue
            aspects = _clean_aspects(
                [
                    {
                        "aspect": AIHUB_ASPECT_MAP.get(a.get("Aspect", "")),
                        "sentiment": AIHUB_POLARITY_MAP.get(str(a.get("SentimentPolarity"))),
                    }
                    for a in r.get("Aspects", [])
                ]
            )
            by_cat[cat].append(
                {
                    "source": "aihub",
                    "category": cat,
                    "product_name": r.get("ProductName"),
                    "rating": _score_to_rating(r.get("ReviewScore")),
                    "style": None,
                    "text": text,
                    "aspects": aspects,
                }
            )
    rows = []
    for cat, items in by_cat.items():
        # 4만 건을 다 넣을 필요는 없어서 카테고리별로 같은 수만 무작위로 뽑는다
        rng.shuffle(items)
        rows.extend(items[:per_category])
    return rows


# ---------------------------------------------------------------- 3. 직접 작성 리뷰
def load_handwritten(folder: Path) -> list[dict]:
    """.local/handwritten/*.csv 를 읽는다. 컬럼: text(필수), category, rating, aspects

    aspects 칸은 "사이즈·핏:부정;배송:긍정" 처럼 '속성:감성' 을 세미콜론으로 이어 쓴다(비워도 됨).
    """
    _guard_private(folder)
    rows = []
    for f in sorted(folder.glob("*.csv")):
        _guard_private(f)
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                text = (r.get("text") or "").strip()
                if not text:
                    continue
                aspects = []
                for part in (r.get("aspects") or "").split(";"):
                    if ":" in part:
                        name, senti = (s.strip() for s in part.split(":", 1))
                        aspects.append({"aspect": name, "sentiment": senti})
                rating = (r.get("rating") or "").strip()
                rows.append(
                    {
                        "source": "handwritten",
                        "category": (r.get("category") or "").strip() or None,
                        "product_name": None,
                        "rating": int(rating) if rating.isdigit() else None,
                        "style": None,
                        "text": text,
                        "aspects": _clean_aspects(aspects),
                    }
                )
    if not rows:
        print(f"  - handwritten: CSV 없음 또는 비어 있음 ({folder})")
    return rows


def build_seeds(args) -> None:
    """args: analysis_dir, handwritten_dir, aihub_per_category, max_len, out, seed (cli.py 의 rsim seeds 옵션)."""

    rng = random.Random(args.seed)
    analysis_dir = Path(args.analysis_dir)
    print("시드 수집 중...")
    rows = (
        load_synth(analysis_dir)
        + load_aihub(analysis_dir, args.aihub_per_category, args.max_len, rng)
        + load_handwritten(Path(args.handwritten_dir))
    )
    if not rows:
        raise SystemExit("시드가 한 건도 없습니다. 경로를 확인하세요.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)

    print(f"완료: {out}  총 {len(rows)}건")
    print("  출처별:", dict(Counter(r["source"] for r in rows)))
    print("  카테고리별:", dict(Counter(r["category"] or "공통" for r in rows)))
