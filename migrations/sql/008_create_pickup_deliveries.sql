ALTER TABLE cargos DROP CONSTRAINT cargos_status_check;
ALTER TABLE cargos ADD CONSTRAINT cargos_status_check CHECK (status IN (
    'received_china', 'consolidated', 'shipped_china', 'in_transit',
    'arrived_tajikistan', 'customs_processing', 'customs_cleared',
    'assigned_pickup', 'domestic_transit', 'arrived_pickup', 'ready_for_pickup'
));

ALTER TABLE consolidations DROP CONSTRAINT consolidations_status_check;
ALTER TABLE consolidations ADD CONSTRAINT consolidations_status_check CHECK (status IN (
    'consolidated_china', 'shipped_china', 'in_transit',
    'arrived_tajikistan', 'customs_processing', 'customs_cleared',
    'assigned_pickup', 'domestic_transit', 'arrived_pickup', 'ready_for_pickup'
));

CREATE TABLE pickup_points (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pickup_code TEXT GENERATED ALWAYS AS ('PP' || lpad(id::text, 6, '0')) STORED,
    city TEXT NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT,
    note TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by_telegram_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pickup_points_code_unique UNIQUE (pickup_code),
    CONSTRAINT pickup_points_city_check CHECK (city IN ('dushanbe', 'khujand')),
    CONSTRAINT pickup_points_name_check CHECK (char_length(btrim(name)) BETWEEN 2 AND 100),
    CONSTRAINT pickup_points_address_check CHECK (char_length(btrim(address)) BETWEEN 5 AND 300),
    CONSTRAINT pickup_points_phone_check CHECK (phone IS NULL OR char_length(btrim(phone)) BETWEEN 5 AND 30),
    CONSTRAINT pickup_points_note_check CHECK (note IS NULL OR char_length(btrim(note)) BETWEEN 2 AND 500)
);

CREATE INDEX pickup_points_active_city_idx ON pickup_points (is_active, city, id);

CREATE TABLE shipment_deliveries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_code TEXT GENERATED ALWAYS AS ('DL' || lpad(id::text, 6, '0')) STORED,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id) ON DELETE RESTRICT,
    client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    pickup_point_id BIGINT NOT NULL REFERENCES pickup_points(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'assigned_pickup',
    assigned_by_telegram_id BIGINT NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ready_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT shipment_deliveries_code_unique UNIQUE (delivery_code),
    CONSTRAINT shipment_deliveries_shipment_client_unique UNIQUE (shipment_id, client_id),
    CONSTRAINT shipment_deliveries_status_check CHECK (status IN (
        'assigned_pickup', 'domestic_transit', 'arrived_pickup', 'ready_for_pickup'
    )),
    CONSTRAINT shipment_deliveries_ready_check CHECK (
        (status = 'ready_for_pickup' AND ready_at IS NOT NULL)
        OR (status <> 'ready_for_pickup' AND ready_at IS NULL)
    )
);

CREATE INDEX shipment_deliveries_client_idx ON shipment_deliveries (client_id, updated_at DESC);
CREATE INDEX shipment_deliveries_status_idx ON shipment_deliveries (status, updated_at DESC);

CREATE TABLE delivery_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_id BIGINT NOT NULL REFERENCES shipment_deliveries(id) ON DELETE CASCADE,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    note TEXT,
    created_by_telegram_id BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT delivery_events_transition_check CHECK (from_status <> to_status),
    CONSTRAINT delivery_events_from_check CHECK (from_status IN (
        'assigned_pickup', 'domestic_transit', 'arrived_pickup', 'ready_for_pickup'
    )),
    CONSTRAINT delivery_events_to_check CHECK (to_status IN (
        'assigned_pickup', 'domestic_transit', 'arrived_pickup', 'ready_for_pickup'
    )),
    CONSTRAINT delivery_events_note_check CHECK (note IS NULL OR char_length(btrim(note)) BETWEEN 2 AND 500),
    CONSTRAINT delivery_events_delivery_status_unique UNIQUE (delivery_id, to_status)
);

CREATE INDEX delivery_events_delivery_occurred_idx ON delivery_events (delivery_id, occurred_at, id);
CREATE INDEX delivery_events_to_status_idx ON delivery_events (to_status);
