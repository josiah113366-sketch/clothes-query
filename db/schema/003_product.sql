-- 상품 시드(Parquet)를 그대로 옮기는 테이블. 컬럼과 타입은 Parquet 스키마에서 만들었다.
-- 컬럼을 바꾸면 simulator/src/sim/product/params.py 의 DESIGN_COLUMNS, VARIANT_COLUMNS도 같이 바꾼다.
-- 시드에 NULL이 없어서 모든 컬럼이 NOT NULL이다. 인덱스는 PK/FK 외에 두지 않는다.

CREATE TABLE product_design (
    product_code       bigint PRIMARY KEY,
    product_type_no    bigint NOT NULL,
    product_type_name  text   NOT NULL,
    product_group_name text   NOT NULL,
    garment_group_no   bigint NOT NULL,
    garment_group_name text   NOT NULL,
    index_group_no     bigint NOT NULL,
    index_group_name   text   NOT NULL,
    design_price       bigint NOT NULL
);

CREATE TABLE product_variant (
    article_id                text   PRIMARY KEY,
    product_code              bigint NOT NULL REFERENCES product_design (product_code),
    prod_name                 text   NOT NULL,
    colour_group_code         bigint NOT NULL,
    colour_group_name         text   NOT NULL,
    graphical_appearance_no   bigint NOT NULL,
    graphical_appearance_name text   NOT NULL,
    price                     bigint NOT NULL
);
