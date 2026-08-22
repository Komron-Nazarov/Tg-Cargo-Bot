CREATE TABLE china_trackings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    tracking_number TEXT NOT NULL,
    tracking_number_normalized TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'declared',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at TIMESTAMPTZ,
    CONSTRAINT china_trackings_number_not_blank
        CHECK (btrim(tracking_number) <> ''),
    CONSTRAINT china_trackings_normalized_not_blank
        CHECK (btrim(tracking_number_normalized) <> ''),
    CONSTRAINT china_trackings_status_check
        CHECK (status IN ('declared', 'cancelled'))
);

CREATE INDEX china_trackings_client_created_idx
    ON china_trackings (client_id, created_at DESC);

CREATE INDEX china_trackings_status_created_idx
    ON china_trackings (status, created_at DESC);
