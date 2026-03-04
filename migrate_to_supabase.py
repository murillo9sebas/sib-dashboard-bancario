"""
migrate_to_supabase.py
──────────────────────
One-time script: reads all local .xls files and bulk-inserts them into Supabase.

Run once after creating the Supabase table:
    python3 migrate_to_supabase.py

Requires .streamlit/secrets.toml with:
    SUPABASE_URL = "https://xxxx.supabase.co"
    SUPABASE_KEY = "your-anon-key"
"""

import os
import sys
import math

# ── Read credentials ──────────────────────────────────────────────────────────

SECRETS_PATH = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")

try:
    if not os.path.exists(SECRETS_PATH):
        raise FileNotFoundError
    secrets = {}
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip().strip('"').strip("'")
except FileNotFoundError:
    print(f"ERROR: secrets.toml no encontrado en {SECRETS_PATH}")
    print("Crea .streamlit/secrets.toml con SUPABASE_URL y SUPABASE_KEY")
    sys.exit(1)

SUPABASE_URL = secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = secrets.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .streamlit/secrets.toml")
    sys.exit(1)

# ── Load data + connect ───────────────────────────────────────────────────────

from supabase import create_client
from data_loader import load_data
import pandas as pd

print("Connecting to Supabase...")
client = create_client(SUPABASE_URL, SUPABASE_KEY)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"Parsing local .xls files from {DATA_DIR} ...")
df = load_data(DATA_DIR)

if df.empty:
    print("ERROR: No .xls files found. Make sure the files are in the same folder.")
    sys.exit(1)

print(f"Loaded {len(df)} records | {df['bank'].nunique()} banks | "
      f"{df['date'].min().strftime('%b %Y')} → {df['date'].max().strftime('%b %Y')}")

# ── Convert and batch-insert ──────────────────────────────────────────────────

def df_to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        rec = {"date": str(row["date"].date()), "bank": row["bank"]}
        numeric_cols = [c for c in df.columns if c not in ("date", "bank")]
        for col in numeric_cols:
            val = row[col]
            rec[col] = None if (val is None or (isinstance(val, float) and math.isnan(val))) else float(val)
        records.append(rec)
    return records

records = df_to_records(df)

BATCH = 200
inserted = 0
skipped  = 0

print(f"Inserting {len(records)} records in batches of {BATCH}...")

for i in range(0, len(records), BATCH):
    batch = records[i : i + BATCH]
    try:
        res = client.table("balance_general").upsert(batch, on_conflict="date,bank", ignore_duplicates=True).execute()
        batch_inserted = len(res.data) if res.data else 0
        inserted += batch_inserted
        skipped  += len(batch) - batch_inserted
        print(f"  Batch {i//BATCH + 1}: {batch_inserted} inserted, {len(batch) - batch_inserted} skipped")
    except Exception as e:
        print(f"  ERROR on batch {i//BATCH + 1}: {e}")

print()
print(f"✅ Migration complete: {inserted} rows inserted, {skipped} duplicates skipped")
print("You can now deploy the Streamlit app and it will read from Supabase.")
