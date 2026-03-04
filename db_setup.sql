-- ============================================================
-- SIB Dashboard — Supabase table setup
-- Run this once in the Supabase SQL Editor (supabase.com → project → SQL Editor)
-- ============================================================

CREATE TABLE IF NOT EXISTS balance_general (
  id                        BIGSERIAL PRIMARY KEY,
  date                      DATE        NOT NULL,
  bank                      TEXT        NOT NULL,
  -- Assets
  disponibilidades          NUMERIC,
  inversiones               NUMERIC,
  cartera_creditos          NUMERIC,
  otras_inversiones         NUMERIC,
  inmuebles_muebles         NUMERIC,
  cargos_diferidos          NUMERIC,
  otros_activos             NUMERIC,
  total_activo_neto         NUMERIC,
  -- Liabilities & Capital
  obligaciones_depositarias NUMERIC,
  creditos_obtenidos        NUMERIC,
  obligaciones_financieras  NUMERIC,
  provisiones               NUMERIC,
  creditos_diferidos        NUMERIC,
  otros_pasivos             NUMERIC,
  otras_cuentas_acreedoras  NUMERIC,
  capital_contable          NUMERIC,
  total_pasivo_capital      NUMERIC,
  -- Prevent duplicate rows for the same bank+month
  UNIQUE (date, bank)
);

-- Optional: index on date for faster range queries
CREATE INDEX IF NOT EXISTS idx_balance_date ON balance_general (date);
CREATE INDEX IF NOT EXISTS idx_balance_bank ON balance_general (bank);
