-- 리뷰 시뮬레이터(review-simulator/)가 쓰는 리뷰 테이블.
-- 결제 후 1~14일 뒤 주문에 리뷰를 단다(2026-10-14 구상). 이 테이블도 member 처럼 CDC → Kafka → S3 로 흘린다.
-- 정답 라벨(속성·감성)은 실제 쇼핑몰에 없는 값이라 넣지 않는다. 시뮬레이터가 .local/ 파일에 따로 둔다.
CREATE TABLE reviews (
    review_id    text        PRIMARY KEY,
    -- 주문 하나에 리뷰 하나. 주문 없이 만든 리뷰(무작위 모드)는 NULL 이다. UNIQUE 는 NULL 여러 개를 허용한다.
    -- [임시] 주문 테이블이 생기면 orders(order_id) 참조로 바꾼다.
    order_id     text        UNIQUE,
    -- [임시] 시뮬레이터 값(C-…). member(member_id) 는 uuid 라서 주문 테이블과 연결할 때 타입을 맞춘다.
    member_id    text        NOT NULL,
    -- [임시] 상품 정보는 상품 테이블이 생기면 product_id 만 남기고 참조로 바꾼다.
    product_id   text        NOT NULL,
    product_name text        NOT NULL,
    category     text        NOT NULL,
    -- [임시] 나중에 member 테이블에서 member_id 와 같이 가져온다.
    age_group    text,
    rating       smallint    NOT NULL CHECK (rating BETWEEN 1 AND 5),
    body         text        NOT NULL,
    source       text        NOT NULL,
    -- 리뷰 작성 시각(업무 시각). 주문 모드에서는 결제 시각 + 1~14일이다.
    written_at   timestamptz NOT NULL,
    -- 행이 DB 에 들어간 시각. 시뮬레이터가 넣지 않고 DB 기본값이 기록한다.
    created_at   timestamptz NOT NULL DEFAULT now()
);
