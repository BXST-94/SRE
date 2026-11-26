-- Esquema SQLite de la muestra (Amazon Reviews 2023, Electronics, 5-core).
-- Version portable del esquema original de PostgreSQL (sql/schema.sql del proyecto completo).
-- Lo usa actividad/crear_bd.py. Los items viven en un CSV aparte (datos_iniciales/items_muestra.csv).

CREATE TABLE IF NOT EXISTS reviews (
    review_id         INTEGER PRIMARY KEY,
    user_id           TEXT    NOT NULL,
    parent_asin       TEXT    NOT NULL,
    asin              TEXT,
    rating            REAL,
    title             TEXT,
    text              TEXT,
    timestamp         INTEGER,   -- milisegundos desde epoch (unidad original de Amazon)
    helpful_vote      INTEGER,
    verified_purchase INTEGER    -- 1 = compra verificada, 0 = no
);

CREATE INDEX IF NOT EXISTS idx_reviews_user      ON reviews (user_id);
CREATE INDEX IF NOT EXISTS idx_reviews_parent    ON reviews (parent_asin);
CREATE INDEX IF NOT EXISTS idx_reviews_timestamp ON reviews (timestamp);
