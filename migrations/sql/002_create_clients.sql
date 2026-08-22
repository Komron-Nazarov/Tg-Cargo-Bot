CREATE TABLE clients (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_code TEXT GENERATED ALWAYS AS (
        'C' || lpad(id::text, 6, '0')
    ) STORED,
    telegram_user_id BIGINT NOT NULL UNIQUE,
    telegram_username TEXT,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    delivery_city TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT clients_client_code_unique UNIQUE (client_code),
    CONSTRAINT clients_full_name_not_blank CHECK (btrim(full_name) <> ''),
    CONSTRAINT clients_phone_not_blank CHECK (btrim(phone) <> ''),
    CONSTRAINT clients_delivery_city_not_blank CHECK (btrim(delivery_city) <> '')
);
