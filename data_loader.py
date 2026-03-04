"""
data_loader.py
──────────────
Parses SIB_balance_general_*.xls files (which are HTML tables in disguise).
Auto-detects all files in the given directory so adding a new file is enough
to have it picked up on the next app reload.
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
import re
from typing import Optional
import pandas as pd


# ── HTML parser ───────────────────────────────────────────────────────────────

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._cur_table: list[list[str]] = []
        self._cur_row: list[str] = []
        self._cur_cell: str = ""
        self._in_cell: bool = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._cur_table = []
        elif tag == "tr":
            self._cur_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cur_cell = ""

    def handle_endtag(self, tag):
        if tag == "table":
            if self._cur_table:
                self.tables.append(self._cur_table)
        elif tag == "tr":
            if self._cur_row:
                self._cur_table.append(self._cur_row)
        elif tag in ("td", "th"):
            self._in_cell = False
            self._cur_row.append(self._cur_cell.strip())
            self._cur_cell = ""

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell += data


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTH_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_date(text: str) -> pd.Timestamp | None:
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", text.lower())
    if m:
        day, month, year = m.groups()
        return pd.Timestamp(int(year), _MONTH_ES.get(month, 1), int(day))
    return None


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _read_file(path: str) -> str:
    """Try encodings in order; cp1252 preserves Spanish accents correctly."""
    for enc in ("cp1252", "latin-1", "utf-8"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ── File parser ───────────────────────────────────────────────────────────────

def _parse_file(path: str) -> list[dict]:
    content = _read_file(path)
    p = _TableParser()
    p.feed(content)

    if len(p.tables) < 4:
        return []

    # Table 0 → header (title, date, currency)
    # Table 1 → ACTIVO NETO data
    # Table 2 → header repeated
    # Table 3 → PASIVO Y CAPITAL data
    # Table 4 → footnotes

    date_str = p.tables[0][1][0] if len(p.tables[0]) > 1 else ""
    date = _parse_date(date_str)
    if date is None:
        return []

    asset_rows = p.tables[1][1:]   # skip column header row
    liab_rows  = p.tables[3][1:]

    # Build liabilities lookup by bank name
    liab_by_bank = {
        r[0]: r for r in liab_rows if r and r[0].upper() != "TOTAL"
    }

    def a(row, i): return _to_float(row[i]) if i < len(row) else None
    def l(row, i): return _to_float(row[i]) if row and i < len(row) else None

    records = []
    for row in asset_rows:
        if not row or row[0].upper() == "TOTAL":
            continue

        bank = row[0]
        lib  = liab_by_bank.get(bank, [])

        records.append({
            "date":                     date,
            "bank":                     bank,
            # ── Assets ──────────────────────────────────────────────────────
            "disponibilidades":         a(row, 1),
            "inversiones":              a(row, 2),
            "cartera_creditos":         a(row, 3),
            "otras_inversiones":        a(row, 4),
            "inmuebles_muebles":        a(row, 5),
            "cargos_diferidos":         a(row, 6),
            "otros_activos":            a(row, 7),
            "total_activo_neto":        a(row, 8),
            # ── Liabilities & Capital ────────────────────────────────────────
            "obligaciones_depositarias": l(lib, 1),
            "creditos_obtenidos":        l(lib, 2),
            "obligaciones_financieras":  l(lib, 3),
            "provisiones":               l(lib, 4),
            "creditos_diferidos":        l(lib, 5),
            "otros_pasivos":             l(lib, 6),
            "otras_cuentas_acreedoras":  l(lib, 7),
            "capital_contable":          l(lib, 8),
            "total_pasivo_capital":      l(lib, 9),
        })
    return records


# ── Public API ────────────────────────────────────────────────────────────────

#: The 5 key metrics used for KPI cards and overview sections
KPI_METRICS: dict[str, str] = {
    "Disponibilidades":       "disponibilidades",
    "Inversiones":            "inversiones",
    "Cartera de Créditos":    "cartera_creditos",
    "Total Activo Neto":      "total_activo_neto",
    "Total Pasivo y Capital": "total_pasivo_capital",
}

#: All 17 available metrics (exposed in the metric selector)
METRICS: dict[str, str] = {
    # Assets
    "Disponibilidades":          "disponibilidades",
    "Inversiones":               "inversiones",
    "Cartera de Créditos":       "cartera_creditos",
    "Otras Inversiones":         "otras_inversiones",
    "Inmuebles y Muebles":       "inmuebles_muebles",
    "Cargos Diferidos":          "cargos_diferidos",
    "Otros Activos":             "otros_activos",
    "Total Activo Neto":         "total_activo_neto",
    # Liabilities & Capital
    "Obligaciones Depositarias": "obligaciones_depositarias",
    "Créditos Obtenidos":        "creditos_obtenidos",
    "Obligaciones Financieras":  "obligaciones_financieras",
    "Provisiones":               "provisiones",
    "Créditos Diferidos":        "creditos_diferidos",
    "Otros Pasivos":             "otros_pasivos",
    "Otras Cuentas Acreedoras":  "otras_cuentas_acreedoras",
    "Capital Contable":          "capital_contable",
    "Total Pasivo y Capital":    "total_pasivo_capital",
}


def load_data(data_dir: str = ".") -> pd.DataFrame:
    """
    Scan *data_dir* for SIB_balance_general_*.xls files, parse them all,
    and return a single DataFrame sorted oldest → newest.

    Adding a new file to the folder and reloading the app is all that is
    needed to include fresh data.
    """
    pattern = re.compile(r"SIB_balance_general_\d+\.xls$", re.IGNORECASE)
    files = sorted(
        [f for f in os.listdir(data_dir) if pattern.match(f)],
        key=lambda x: int(re.search(r"(\d+)", x).group()),
    )

    all_records: list[dict] = []
    for fname in files:
        all_records.extend(_parse_file(os.path.join(data_dir, fname)))

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records).sort_values("date").reset_index(drop=True)
    return df


def compute_changes(df: pd.DataFrame, bank: str, col: str) -> pd.DataFrame:
    """
    Return a DataFrame for *bank* with MoM %, YoY %, and YTD % columns.

    MoM  = change vs prior month
    YoY  = change vs same month prior year
    YTD  = change vs January of the same year
    """
    bdf = (
        df[df["bank"] == bank][["date", col]]
        .sort_values("date")
        .copy()
        .reset_index(drop=True)
    )

    bdf["mom"] = bdf[col].pct_change() * 100
    bdf["yoy"] = bdf[col].pct_change(12) * 100

    # YTD: relative to the January value of the same year
    jan_cache: dict[int, float] = {}
    ytd_vals: list[float | None] = []
    for _, row in bdf.iterrows():
        yr = row["date"].year
        if yr not in jan_cache:
            jan = bdf[(bdf["date"].dt.year == yr) & (bdf["date"].dt.month == 1)]
            jan_cache[yr] = jan.iloc[0][col] if not jan.empty else None
        base = jan_cache[yr]
        if base and base != 0 and pd.notna(row[col]):
            ytd_vals.append((row[col] - base) / base * 100)
        else:
            ytd_vals.append(None)
    bdf["ytd"] = ytd_vals

    return bdf


def compute_system_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate all banks by date and compute system-wide changes."""
    cols = list(METRICS.values())
    total = df.groupby("date")[cols].sum().reset_index().sort_values("date")
    for col in cols:
        total[f"{col}_mom"] = total[col].pct_change() * 100
        total[f"{col}_yoy"] = total[col].pct_change(12) * 100
    return total


# ── Supabase integration ──────────────────────────────────────────────────────

def load_from_supabase(client) -> pd.DataFrame:
    """
    Query all rows from Supabase `balance_general` table and return
    a DataFrame with the same structure as `load_data()`.
    """
    import math

    # Supabase returns max 1000 rows by default — paginate to get all
    all_rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        res = (
            client.table("balance_general")
            .select("*")
            .order("date", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = res.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    # Drop internal Supabase id column if present
    df = df.drop(columns=["id"], errors="ignore")
    df["date"] = pd.to_datetime(df["date"])
    # Ensure numeric columns are float (Supabase may return strings)
    numeric_cols = [c for c in df.columns if c not in ("date", "bank")]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def insert_file_to_supabase(client, file_content: str | bytes, filename: str) -> int:
    """
    Parse a single .xls file (as string or bytes) and upsert records to Supabase.
    Returns the number of new rows inserted (duplicates are silently skipped).
    """
    import math
    import tempfile

    # Write to a temp file so _parse_file() can read it
    suffix = ".xls"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as tmp:
        if isinstance(file_content, str):
            tmp.write(file_content.encode("cp1252", errors="replace"))
        else:
            tmp.write(file_content)
        tmp_path = tmp.name

    try:
        records_raw = _parse_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    if not records_raw:
        return 0

    # Convert to Supabase-friendly format
    records = []
    for r in records_raw:
        row = {"date": str(r["date"].date()), "bank": r["bank"]}
        for col in [c for c in r if c not in ("date", "bank")]:
            val = r[col]
            row[col] = None if (val is None or (isinstance(val, float) and math.isnan(val))) else float(val)
        records.append(row)

    res = (
        client.table("balance_general")
        .upsert(records, on_conflict="date,bank", ignore_duplicates=True)
        .execute()
    )
    return len(res.data) if res.data else 0


def compute_bank_vs_system(df: pd.DataFrame, bank: str) -> pd.DataFrame:
    """
    For every date and every metric column, compute the selected bank's
    value, the system total, and the bank's % share.

    Returns a DataFrame with columns:
        date, metric, bank_value, system_total, share_pct,
        mom_bank, mom_system
    sorted by metric then date.
    """
    cols = list(METRICS.values())
    system = df.groupby("date")[cols].sum().reset_index().sort_values("date")
    bank_df = (
        df[df["bank"] == bank][["date"] + cols]
        .sort_values("date")
        .reset_index(drop=True)
    )

    rows = []
    for col in cols:
        b = bank_df[["date", col]].rename(columns={col: "bank_value"})
        s = system[["date", col]].rename(columns={col: "system_total"})
        merged = b.merge(s, on="date").dropna(subset=["bank_value", "system_total"])
        merged["share_pct"]   = merged["bank_value"] / merged["system_total"] * 100
        merged["mom_bank"]    = merged["bank_value"].pct_change() * 100
        merged["mom_system"]  = merged["system_total"].pct_change() * 100
        merged["metric"]      = col
        rows.append(merged)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values(["metric", "date"])
