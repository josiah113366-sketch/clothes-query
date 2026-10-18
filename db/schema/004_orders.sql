-- 거래 테이블 3개 (orders, order_items, payments). 컬럼은 거래 설계 3-2절을 따른다.
-- order_items.article_id가 product_variant를 참조하므로 003_product.sql이 먼저 적용되어야 한다.
-- 시각은 모두 timestamptz다. updated_at은 실제 UPDATE 시각이 아니라 상태가 바뀌기로 한 (예정된) 시각을 넣는다.
-- 인덱스는 PK/UNIQUE 외에 두지 않는다.

CREATE TABLE orders (
    order_id      uuid        PRIMARY KEY,
    member_id     uuid        NOT NULL REFERENCES members (member_id),
    session_id    uuid        NOT NULL,
    status        text        NOT NULL CHECK (status IN (
        'PLACED', 'PAID', 'SHIPPED', 'DELIVERED', 'PAYMENT_FAILED', 'CANCELLED', 'REFUNDED'
    )),
    status_reason text,
    total_amount  bigint      NOT NULL CHECK (total_amount > 0),
    ordered_at    timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL,
    CONSTRAINT orders_status_reason_check CHECK (
        (status = 'CANCELLED' AND status_reason = 'USER_REQUEST')
        OR (status = 'REFUNDED' AND status_reason = 'RETURN')
        OR (status NOT IN ('CANCELLED', 'REFUNDED') AND status_reason IS NULL)
    ),
    CONSTRAINT orders_updated_after_ordered_check CHECK (updated_at >= ordered_at)
);

CREATE TABLE order_items (
    order_item_id uuid   PRIMARY KEY,
    order_id      uuid   NOT NULL REFERENCES orders (order_id),
    article_id    text   NOT NULL REFERENCES product_variant (article_id),
    quantity      integer NOT NULL CHECK (quantity >= 1),
    unit_price    bigint NOT NULL CHECK (unit_price > 0)
);

-- 결제 시도 1번 = 1행. INSERT만 하고 고치지 않는다 (재시도는 attempt_no가 다른 새 행).
CREATE TABLE payments (
    payment_id    uuid        PRIMARY KEY,
    order_id      uuid        NOT NULL REFERENCES orders (order_id),
    attempt_no    integer     NOT NULL CHECK (attempt_no >= 1),
    method        text        NOT NULL CHECK (method IN ('CARD', 'SIMPLE_PAY', 'BANK_TRANSFER')),
    pg            text        NOT NULL CHECK (pg IN ('PG_A', 'PG_B')),
    amount        bigint      NOT NULL CHECK (amount > 0),
    status        text        NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    failure_code  text        CHECK (failure_code IN (
        'INSUFFICIENT_BALANCE', 'CARD_LIMIT_EXCEEDED', 'CARD_DECLINED', 'PG_TIMEOUT', 'PG_ERROR'
    )),
    requested_at  timestamptz NOT NULL,
    completed_at  timestamptz NOT NULL,
    CONSTRAINT payments_order_attempt_key UNIQUE (order_id, attempt_no),
    CONSTRAINT payments_status_failure_code_check CHECK (
        (status = 'SUCCESS' AND failure_code IS NULL)
        OR (status = 'FAILED' AND failure_code IS NOT NULL)
    ),
    CONSTRAINT payments_completed_after_requested_check CHECK (completed_at >= requested_at)
);