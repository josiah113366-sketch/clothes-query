CREATE TABLE member_archive (
    member_id   uuid        PRIMARY KEY REFERENCES member (member_id),
    name        text        NOT NULL,
    email       text        NOT NULL,
    phone       text        NOT NULL,
    archived_at timestamptz NOT NULL DEFAULT now()
);
