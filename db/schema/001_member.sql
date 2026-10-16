CREATE TABLE members (
    member_id         uuid        PRIMARY KEY,
    name              text,
    email             text        UNIQUE,
    phone             text        UNIQUE,
    birth_date        date,
    gender            text        NOT NULL CHECK (gender IN ('F', 'M')),
    signup_at         timestamptz NOT NULL,
    signup_channel    text        NOT NULL CHECK (signup_channel IN ('web', 'app')),
    marketing_consent boolean     NOT NULL,
    status            text        NOT NULL CHECK (status IN ('ACTIVE', 'WITHDRAWN')),
    withdrawn_at      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    password_hash     text,
    region_sigungu    text        NOT NULL,
    age_band          text        NOT NULL
        CHECK (age_band IN ('~19', '20s', '30s', '40s', '50s', '60s', '70+')),
    CONSTRAINT members_status_withdrawn_at_check CHECK (
        (status = 'ACTIVE' AND withdrawn_at IS NULL)
        OR (status = 'WITHDRAWN' AND withdrawn_at IS NOT NULL)
    ),
    CONSTRAINT members_withdrawn_after_signup_check CHECK (
        withdrawn_at IS NULL OR withdrawn_at >= signup_at
    )
);
