ALTER TABLE shipment_deliveries DROP CONSTRAINT shipment_deliveries_status_check;
ALTER TABLE shipment_deliveries ADD CONSTRAINT shipment_deliveries_status_check CHECK (status IN (
    'assigned_pickup','domestic_transit','arrived_pickup','ready_for_pickup','handed_over','completed'
));
ALTER TABLE shipment_deliveries DROP CONSTRAINT shipment_deliveries_ready_check;
ALTER TABLE shipment_deliveries ADD CONSTRAINT shipment_deliveries_ready_check CHECK (
    (status IN ('ready_for_pickup','handed_over','completed') AND ready_at IS NOT NULL)
    OR (status NOT IN ('ready_for_pickup','handed_over','completed') AND ready_at IS NULL)
);

ALTER TABLE cargos DROP CONSTRAINT cargos_status_check;
ALTER TABLE cargos ADD CONSTRAINT cargos_status_check CHECK (status IN (
    'received_china','consolidated','shipped_china','in_transit','arrived_tajikistan',
    'customs_processing','customs_cleared','assigned_pickup','domestic_transit',
    'arrived_pickup','ready_for_pickup','handed_over','completed'
));

ALTER TABLE consolidations DROP CONSTRAINT consolidations_status_check;
ALTER TABLE consolidations ADD CONSTRAINT consolidations_status_check CHECK (status IN (
    'consolidated_china','shipped_china','in_transit','arrived_tajikistan',
    'customs_processing','customs_cleared','assigned_pickup','domestic_transit',
    'arrived_pickup','ready_for_pickup','handed_over','completed'
));

CREATE TABLE handover_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_id BIGINT NOT NULL REFERENCES shipment_deliveries(id) ON DELETE RESTRICT,
    recipient_type TEXT NOT NULL,
    recipient_name TEXT NOT NULL,
    recipient_phone TEXT,
    note TEXT,
    handed_over_by_telegram_id BIGINT NOT NULL,
    handed_over_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT handover_records_delivery_unique UNIQUE(delivery_id),
    CONSTRAINT handover_records_type_check CHECK(recipient_type IN ('client','representative')),
    CONSTRAINT handover_records_name_check CHECK(char_length(btrim(recipient_name)) BETWEEN 2 AND 150),
    CONSTRAINT handover_records_phone_check CHECK(recipient_phone IS NULL OR char_length(btrim(recipient_phone)) BETWEEN 5 AND 30),
    CONSTRAINT handover_records_note_check CHECK(note IS NULL OR char_length(btrim(note)) BETWEEN 2 AND 500)
);
CREATE INDEX handover_records_date_idx ON handover_records(handed_over_at DESC);

CREATE TABLE payment_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_code TEXT GENERATED ALWAYS AS ('PY' || lpad(id::text,6,'0')) STORED,
    delivery_id BIGINT NOT NULL REFERENCES shipment_deliveries(id) ON DELETE RESTRICT,
    amount NUMERIC(14,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'TJS',
    payment_method TEXT NOT NULL,
    reference TEXT,
    note TEXT,
    recorded_by_telegram_id BIGINT NOT NULL,
    paid_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payment_records_code_unique UNIQUE(payment_code),
    CONSTRAINT payment_records_delivery_unique UNIQUE(delivery_id),
    CONSTRAINT payment_records_amount_check CHECK(amount > 0),
    CONSTRAINT payment_records_currency_check CHECK(currency='TJS'),
    CONSTRAINT payment_records_method_check CHECK(payment_method IN ('cash','bank_transfer','other')),
    CONSTRAINT payment_records_reference_check CHECK(reference IS NULL OR char_length(btrim(reference)) BETWEEN 2 AND 100),
    CONSTRAINT payment_records_note_check CHECK(note IS NULL OR char_length(btrim(note)) BETWEEN 2 AND 500)
);
CREATE INDEX payment_records_paid_idx ON payment_records(paid_at DESC);
CREATE INDEX payment_records_method_idx ON payment_records(payment_method,paid_at DESC);
