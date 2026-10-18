"""디자인·상품 기준정보 스냅샷을 원천 DDL의 컬럼으로 정리한다."""
from __future__ import annotations

import argparse

from .common import RowError, collect_unique, integer, required_text, run_local

CHECK_VERSION = "products.v1"
DESIGN_INTEGERS = ("product_code", "product_type_no", "garment_group_no", "index_group_no", "design_price")
DESIGN_TEXT = ("product_type_name", "product_group_name", "garment_group_name", "index_group_name")
VARIANT_INTEGERS = ("product_code", "colour_group_code", "graphical_appearance_no", "price")
VARIANT_TEXT = ("article_id", "prod_name", "colour_group_name", "graphical_appearance_name")


def build_products(designs: list[dict], variants: list[dict]) -> dict[str, list[dict]]:
    def design(raw):
        return {**{field: integer(raw, field) for field in DESIGN_INTEGERS},
                **{field: required_text(raw, field) for field in DESIGN_TEXT}}

    clean_designs, design_errors, design_summary = collect_unique(
        designs, "product_design", "product_code", design, CHECK_VERSION,
    )
    codes = {row["product_code"] for row in clean_designs}
    supplied_codes = {raw["product_code"] for raw in designs if isinstance(raw, dict)
                      and isinstance(raw.get("product_code"), int) and not isinstance(raw["product_code"], bool)}

    def variant(raw):
        row = {**{field: integer(raw, field) for field in VARIANT_INTEGERS},
               **{field: required_text(raw, field) for field in VARIANT_TEXT}}
        if row["product_code"] not in codes:
            code = "DEPENDENCY_BLOCKED" if row["product_code"] in supplied_codes else "PENDING_REFERENCE"
            raise RowError("product_code", code, "연결할 정상 디자인 기준정보가 없습니다")
        return row

    clean_variants, variant_errors, variant_summary = collect_unique(
        variants, "product_variant", "article_id", variant, CHECK_VERSION,
    )
    design_summary["output_counts"] = {"silver_product_design": len(clean_designs)}
    variant_summary["output_counts"] = {"silver_product_variant": len(clean_variants)}
    return {
        "silver_product_design": clean_designs, "silver_product_variant": clean_variants,
        "quarantined_records": design_errors + variant_errors,
        "dq_results": [design_summary, variant_summary],
    }


def run(designs_input: str, variants_input: str, output_root: str) -> dict:
    return run_local({"designs": designs_input, "variants": variants_input}, output_root,
                     "products", CHECK_VERSION,
                     lambda rows: build_products(rows["designs"], rows["variants"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="문서 기준 상품 기준정보 JSONL → 로컬 Silver")
    parser.add_argument("--designs-input", required=True)
    parser.add_argument("--variants-input", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    manifest = run(args.designs_input, args.variants_input, args.output_root)
    print(f"상품 Silver {manifest['status']}: {manifest['output_counts']}")
    print(f"대표 결과: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
