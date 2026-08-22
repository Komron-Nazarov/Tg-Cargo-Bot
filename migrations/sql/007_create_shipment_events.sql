ALTER TABLE shipments DROP CONSTRAINT shipments_status_check;
ALTER TABLE shipments ADD CONSTRAINT shipments_status_check CHECK (
    status IN (
        'departed_china', 'in_transit', 'arrived_tajikistan',
        'customs_processing', 'customs_cleared'
    )
);

ALTER TABLE cargos DROP CONSTRAINT cargos_status_check;
ALTER TABLE cargos ADD CONSTRAINT cargos_status_check CHECK (
    status IN (
        'received_china', 'consolidated', 'shipped_china', 'in_transit',
        'arrived_tajikistan', 'customs_processing', 'customs_cleared'
    )
);

ALTER TABLE consolidations DROP CONSTRAINT consolidations_status_check;
ALTER TABLE consolidations ADD CONSTRAINT consolidations_status_check CHECK (
    status IN (
        'consolidated_china', 'shipped_china', 'in_transit',
        'arrived_tajikistan', 'customs_processing', 'customs_cleared'
    )
);

CREATE TABLE shipment_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    note TEXT,
    created_by_telegram_id BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT shipment_events_transition_check CHECK (from_status <> to_status),
    CONSTRAINT shipment_events_from_status_check CHECK (
        from_status IN (
            'departed_china', 'in_transit', 'arrived_tajikistan',
            'customs_processing', 'customs_cleared'
        )
    ),
    CONSTRAINT shipment_events_to_status_check CHECK (
        to_status IN (
            'departed_china', 'in_transit', 'arrived_tajikistan',
            'customs_processing', 'customs_cleared'
        )
    ),
    CONSTRAINT shipment_events_note_check CHECK (
        note IS NULL OR char_length(btrim(note)) BETWEEN 2 AND 500
    ),
    CONSTRAINT shipment_events_shipment_status_unique UNIQUE (shipment_id, to_status)
);

CREATE INDEX shipment_events_shipment_occurred_idx
    ON shipment_events (shipment_id, occurred_at, id);
CREATE INDEX shipment_events_to_status_idx ON shipment_events (to_status);
