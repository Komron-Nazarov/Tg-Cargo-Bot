ALTER TABLE china_trackings
    DROP CONSTRAINT china_trackings_status_check;

ALTER TABLE china_trackings
    ADD CONSTRAINT china_trackings_status_check
    CHECK (status IN ('declared', 'cancelled', 'received'));

CREATE TABLE cargos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cargo_code TEXT GENERATED ALWAYS AS (
        'CG' || lpad(id::text, 6, '0')
    ) STORED,
    client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    china_tracking_id BIGINT NOT NULL UNIQUE
        REFERENCES china_trackings(id) ON DELETE RESTRICT,
    description TEXT,
    actual_weight_kg NUMERIC(12, 3) NOT NULL,
    volume_m3 NUMERIC(8, 4),
    pieces_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'received_china',
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_by_telegram_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT cargos_cargo_code_unique UNIQUE (cargo_code),
    CONSTRAINT cargos_description_not_blank
        CHECK (description IS NULL OR btrim(description) <> ''),
    CONSTRAINT cargos_actual_weight_positive CHECK (actual_weight_kg > 0),
    CONSTRAINT cargos_volume_positive CHECK (volume_m3 IS NULL OR volume_m3 > 0),
    CONSTRAINT cargos_pieces_positive CHECK (pieces_count > 0),
    CONSTRAINT cargos_status_check CHECK (status IN ('received_china'))
);

CREATE INDEX cargos_client_received_idx
    ON cargos (client_id, received_at DESC);

CREATE INDEX cargos_status_received_idx
    ON cargos (status, received_at DESC);

CREATE TABLE cargo_photos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cargo_id BIGINT NOT NULL REFERENCES cargos(id) ON DELETE CASCADE,
    telegram_file_id TEXT NOT NULL,
    telegram_file_unique_id TEXT NOT NULL,
    position SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT cargo_photos_file_id_not_blank
        CHECK (btrim(telegram_file_id) <> ''),
    CONSTRAINT cargo_photos_unique_id_not_blank
        CHECK (btrim(telegram_file_unique_id) <> ''),
    CONSTRAINT cargo_photos_position_check CHECK (position BETWEEN 1 AND 10),
    CONSTRAINT cargo_photos_cargo_position_unique UNIQUE (cargo_id, position),
    CONSTRAINT cargo_photos_cargo_file_unique UNIQUE (
        cargo_id, telegram_file_unique_id
    )
);

CREATE INDEX cargo_photos_cargo_idx ON cargo_photos (cargo_id, position);
