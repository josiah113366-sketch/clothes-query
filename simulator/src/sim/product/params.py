"""상품 적재에 쓰는 수치와 이름. 값은 이 파일 한 곳에만 둔다 (DDL은 db/schema/003_product.sql)."""

DESIGN_TABLE = "product_design"
VARIANT_TABLE = "product_variant"
TABLES = (DESIGN_TABLE, VARIANT_TABLE)  # 적재 순서: design 먼저, variant 나중

DEFAULT_SEED_DIR = ".local/seed_v2"  # simulator/ 기준
S3_REGION = "ap-northeast-1"
S3_SCHEME = "s3://"
S3_READ_TIMEOUT_SECONDS = 30

# (컬럼 이름, PostgreSQL 타입). Parquet 순서 그대로이고, COPY 순서이기도 하다.
DESIGN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("product_code", "BIGINT"),
    ("product_type_no", "BIGINT"),
    ("product_type_name", "TEXT"),
    ("product_group_name", "TEXT"),
    ("garment_group_no", "BIGINT"),
    ("garment_group_name", "TEXT"),
    ("index_group_no", "BIGINT"),
    ("index_group_name", "TEXT"),
    ("design_price", "BIGINT"),
)
VARIANT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("article_id", "TEXT"),
    ("product_code", "BIGINT"),
    ("prod_name", "TEXT"),
    ("colour_group_code", "BIGINT"),
    ("colour_group_name", "TEXT"),
    ("graphical_appearance_no", "BIGINT"),
    ("graphical_appearance_name", "TEXT"),
    ("price", "BIGINT"),
)
COLUMNS = {DESIGN_TABLE: DESIGN_COLUMNS, VARIANT_TABLE: VARIANT_COLUMNS}
KEY_COLUMN = {DESIGN_TABLE: "product_code", VARIANT_TABLE: "article_id"}

# 팀 결정(설명문·이미지·한국어 현지화 컬럼은 쓰지 않는다)과 어긋나는 컬럼 이름 조각
FORBIDDEN_NAME_PARTS = ("desc", "image", "img", "_ko")

DEFAULT_BATCH_SIZE = 5_000
MIN_BATCH_SIZE = 100
MAX_BATCH_SIZE = 50_000

# verify
UNKNOWN_WORD = "unknown"  # 대소문자 무시
PRICE_MIN = 5_900
PRICE_STEP = 500  # 5,900부터 500원 단위 → 끝자리가 900 또는 400 (사용자 결정)
SAMPLE_SIZE = 1_000
SAMPLE_SEED = 20261016  # 샘플 대조는 시드를 고정해 같은 행을 본다
MAX_EXAMPLES = 5
