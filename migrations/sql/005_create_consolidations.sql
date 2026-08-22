ALTER TABLE cargos
    DROP CONSTRAINT cargos_status_check;

ALTER TABLE cargos
    ADD CONSTRAINT cargos_status_check
    CHECK (status IN ('received_china', 'consolidated'));

CREATE TABLE consolidations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consolidation_code TEXT GENERATED ALWAYS AS (
        'CS' || lpad(id::text, 6, '0')
    ) STORED,
    client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    description TEXT,
    final_weight_kg NUMERIC(12, 3) NOT NULL,
    final_volume_m3 NUMERIC(8, 4),
    final_pieces_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'consolidated_china',
    consolidated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consolidated_by_telegram_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT consolidations_code_unique UNIQUE (consolidation_code),
    CONSTRAINT consolidations_description_not_blank
        CHECK (description IS NULL OR btrim(description) <> ''),
    CONSTRAINT consolidations_weight_positive CHECK (final_weight_kg > 0),
    CONSTRAINT consolidations_volume_positive
        CHECK (final_volume_m3 IS NULL OR final_volume_m3 > 0),
    CONSTRAINT consolidations_pieces_positive CHECK (final_pieces_count > 0),
    CONSTRAINT consolidations_status_check
        CHECK (status IN ('consolidated_china'))
);

CREATE INDEX consolidations_client_date_idx
    ON consolidations (client_id, consolidated_at DESC);

CREATE INDEX consolidations_status_date_idx
    ON consolidations (status, consolidated_at DESC);

CREATE TABLE consolidation_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consolidation_id BIGINT NOT NULL
        REFERENCES consolidations(id) ON DELETE CASCADE,
    cargo_id BIGINT NOT NULL REFERENCES cargos(id) ON DELETE RESTRICT,
    position SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT consolidation_items_cargo_unique UNIQUE (cargo_id),
    CONSTRAINT consolidation_items_position_check CHECK (position BETWEEN 1 AND 50),
    CONSTRAINT consolidation_items_consolidation_position_unique
        UNIQUE (consolidation_id, position)
);

CREATE INDEX consolidation_items_consolidation_idx
    ON consolidation_items (consolidation_id, position);

CREATE TABLE consolidation_photos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consolidation_id BIGINT NOT NULL
        REFERENCES consolidations(id) ON DELETE CASCADE,
    telegram_file_id TEXT NOT NULL,
    telegram_file_unique_id TEXT NOT NULL,
    position SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT consolidation_photos_file_id_not_blank
        CHECK (btrim(telegram_file_id) <> ''),
    CONSTRAINT consolidation_photos_unique_id_not_blank
        CHECK (btrim(telegram_file_unique_id) <> ''),
    CONSTRAINT consolidation_photos_position_check CHECK (position BETWEEN 1 AND 10),
    CONSTRAINT consolidation_photos_position_unique
        UNIQUE (consolidation_id, position),
    CONSTRAINT consolidation_photos_file_unique
        UNIQUE (consolidation_id, telegram_file_unique_id)
);

CREATE INDEX consolidation_photos_consolidation_idx
    ON consolidation_photos (consolidation_id, position);
