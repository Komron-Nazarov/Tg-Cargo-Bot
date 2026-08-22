ALTER TABLE cargos DROP CONSTRAINT cargos_status_check;
ALTER TABLE cargos ADD CONSTRAINT cargos_status_check
    CHECK (status IN ('received_china', 'consolidated', 'shipped_china'));

ALTER TABLE consolidations DROP CONSTRAINT consolidations_status_check;
ALTER TABLE consolidations ADD CONSTRAINT consolidations_status_check
    CHECK (status IN ('consolidated_china', 'shipped_china'));

CREATE TABLE shipments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shipment_code TEXT GENERATED ALWAYS AS (
        'SH' || lpad(id::text, 6, '0')
    ) STORED,
    transport_type TEXT NOT NULL,
    transport_reference TEXT,
    note TEXT,
    origin_country TEXT NOT NULL DEFAULT 'CN',
    destination_country TEXT NOT NULL DEFAULT 'TJ',
    status TEXT NOT NULL DEFAULT 'departed_china',
    departed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_telegram_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT shipments_code_unique UNIQUE (shipment_code),
    CONSTRAINT shipments_transport_check
        CHECK (transport_type IN ('truck', 'air', 'rail', 'other')),
    CONSTRAINT shipments_status_check CHECK (status IN ('departed_china')),
    CONSTRAINT shipments_origin_check CHECK (origin_country = 'CN'),
    CONSTRAINT shipments_destination_check CHECK (destination_country = 'TJ'),
    CONSTRAINT shipments_reference_not_blank
        CHECK (transport_reference IS NULL OR btrim(transport_reference) <> ''),
    CONSTRAINT shipments_note_not_blank CHECK (note IS NULL OR btrim(note) <> '')
);

CREATE INDEX shipments_departed_idx ON shipments (departed_at DESC);
CREATE INDEX shipments_status_departed_idx ON shipments (status, departed_at DESC);

CREATE TABLE shipment_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    cargo_id BIGINT REFERENCES cargos(id) ON DELETE RESTRICT,
    consolidation_id BIGINT REFERENCES consolidations(id) ON DELETE RESTRICT,
    position SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT shipment_items_exactly_one_object CHECK (
        (cargo_id IS NOT NULL AND consolidation_id IS NULL)
        OR (cargo_id IS NULL AND consolidation_id IS NOT NULL)
    ),
    CONSTRAINT shipment_items_position_check CHECK (position BETWEEN 1 AND 200),
    CONSTRAINT shipment_items_shipment_position_unique UNIQUE (shipment_id, position)
);

CREATE UNIQUE INDEX shipment_items_cargo_unique
    ON shipment_items (cargo_id) WHERE cargo_id IS NOT NULL;
CREATE UNIQUE INDEX shipment_items_consolidation_unique
    ON shipment_items (consolidation_id) WHERE consolidation_id IS NOT NULL;
CREATE INDEX shipment_items_shipment_idx ON shipment_items (shipment_id, position);
