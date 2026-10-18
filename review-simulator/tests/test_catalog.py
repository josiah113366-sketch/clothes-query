"""상품 정보(catalog.py)와 프롬프트·옵션 연결 테스트 (2026-10-16). LLM 은 부르지 않는다."""

import json
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from rsim.cli import app
from rsim.common.rng import make_rng
from rsim.review.catalog import Catalog, CsvProductSource
from rsim.review.generator import SYSTEM_TEMPLATE, build_user_prompt
from rsim.review.options import pick_options
from rsim.review.scenario import ReviewSpec

runner = CliRunner()

# category 컬럼 없이 상품 정보만 (2026-10-16 lemin: category 는 받지 않는다)
CSV = (
    "product_id,product_name,product_type,material,color,description\n"
    "W-0001,린넨 셔츠,셔츠,린넨 100%,화이트,얇은 셔츠\n"
    "M-0001,니트,,,,\n"
    "S-0001,러닝화,운동화,,,\n"
)
# H&M articles.csv 컬럼 이름으로 와도 읽는다 (index_group_name 같은 분류 컬럼은 쓰지 않는다)
HM_CSV = (
    "article_id,prod_name,index_group_name,product_type_name,colour_group_name,detail_desc\n"
    "0108775015,Strap top,Ladieswear,Vest top,Black,Jersey top with narrow shoulder straps.\n"
)


def _csv(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "products.csv"
    p.write_text(body, encoding="utf-8")
    return p


def _reviews() -> list[dict]:
    path = Path(".local/out/reviews.jsonl")
    return [json.loads(x) for x in path.read_text("utf-8").splitlines()]


def test_csv_source_reads_info_without_category(tmp_path) -> None:
    products = CsvProductSource(_csv(tmp_path, CSV)).load()
    assert [p.product_id for p in products] == ["W-0001", "M-0001", "S-0001"]
    assert all(p.category is None for p in products)
    assert products[0].info == {
        "product_type": "셔츠",
        "material": "린넨 100%",
        "color": "화이트",
        "description": "얇은 셔츠",
    }
    assert products[1].info == {}  # 빈 칸은 넣지 않는다

    hm = CsvProductSource(_csv(tmp_path, HM_CSV)).load()[0]
    assert (hm.product_id, hm.product_name, hm.category) == ("0108775015", "Strap top", None)
    assert hm.info["product_type"] == "Vest top" and hm.info["color"] == "Black"


def test_prompt_has_product_info_only_when_present(tmp_path) -> None:
    catalog = Catalog.build(_csv(tmp_path, CSV), {}, make_rng(0))
    with_info, without = catalog.by_id["W-0001"], catalog.by_id["M-0001"]

    def spec(p):
        return ReviewSpec(
            spec_id="s1",
            product=p,
            created_at=datetime(2026, 10, 8),
            rating=2,
            aspects=[{"aspect": "재질·촉감", "sentiment": "부정"}],
            style="짧은 음슴체",
            length="short",
        )

    prompt = build_user_prompt([spec(with_info)], [])
    payload = json.loads(prompt.split("## 이번에 쓸 리뷰 명세\n", 1)[1])
    assert payload[0]["product_info"] == {
        "상품 종류": "셔츠",
        "소재": "린넨 100%",
        "색상": "화이트",
        "상품 설명": "얇은 셔츠",
    }
    assert "category" not in payload[0]  # category 없는 상품은 명세에서도 뺀다
    assert "product_info" not in build_user_prompt([spec(without)], [])
    assert "product_info" in SYSTEM_TEMPLATE  # 묶음 D


def test_option_color_and_size_from_product() -> None:
    plain = pick_options("여성의류", make_rng(3))
    colored = pick_options("여성의류", make_rng(3), "Dark Blue")
    assert colored["option_color"] == "네이비"  # 영어 색상은 옵션 이름으로
    assert colored["option_size"] == plain["option_size"]
    assert colored["has_photo"] == plain["has_photo"]  # 뒤의 난수가 밀리지 않는다
    assert pick_options("잡화", make_rng(3), "민트")["option_color"] == "민트"  # 표에 없으면 그대로

    # category 가 없으면 상품 종류로 사이즈 묶음을 고른다
    assert pick_options(None, make_rng(3), product_type="러닝 운동화")["option_size"].isdigit()
    assert pick_options(None, make_rng(3), product_type="Bag")["option_size"] == "FREE"
    clothing = {"XS", "S", "M", "L", "XL", "XXL"}
    assert pick_options(None, make_rng(3), product_type="셔츠")["option_size"] in clothing


def test_run_with_products_csv_keeps_review_columns(workdir) -> None:
    # 상품 정보가 있어도 리뷰 이벤트 컬럼은 늘어나지 않는다 (상품 정보는 프롬프트에만)
    args = ["run", "--llm", "fake", "--sink", "jsonl", "--count", "8"]
    assert runner.invoke(app, args).exit_code == 0
    before = _reviews()
    Path(".local/out/reviews.jsonl").unlink()

    (workdir / "data").mkdir(exist_ok=True)
    _csv(workdir / "data", CSV)
    res = runner.invoke(app, args)
    assert res.exit_code == 0, res.output
    after = _reviews()
    assert {tuple(sorted(r)) for r in after} == {tuple(sorted(before[0]))}
    assert {r["category"] for r in after} == {None}  # category 를 안 받으면 null
    for r in after:
        if r["product_id"] == "W-0001":
            assert r["option_color"] == "화이트"
        if r["product_id"] == "S-0001":
            assert r["option_size"].isdigit()  # 운동화 → 신발 사이즈
