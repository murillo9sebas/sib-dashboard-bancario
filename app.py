"""
app.py — SIB Dashboard Bancario Guatemala
==========================================
Ejecutar con:   streamlit run app.py

Para actualizar con nuevos datos:
  - Subir el nuevo .xls desde el sidebar → se inserta en Supabase → dashboard actualiza.

Credenciales (local): .streamlit/secrets.toml
Credenciales (Streamlit Cloud): Settings → Secrets
"""

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import (
    METRICS, KPI_METRICS, compute_changes, compute_system_totals,
    compute_bank_vs_system, load_data, load_from_supabase, insert_file_to_supabase,
)

# ── Configuración ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SIB — Dashboard Bancario",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
COLORS   = px.colors.qualitative.Set2 + px.colors.qualitative.Pastel1

# ── Supabase client ───────────────────────────────────────────────────────────

def _get_supabase_client():
    from supabase import create_client
    url = st.secrets.get("SUPABASE_URL", "").strip()
    key = st.secrets.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None, "SUPABASE_URL o SUPABASE_KEY no configurados"
    try:
        client = create_client(url, key)
        return client, None
    except Exception as e:
        return None, str(e)

_supabase, _supabase_error = _get_supabase_client()

# ── Estilos ───────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    /* Compact metric deltas */
    [data-testid="stMetricDelta"] { font-size: 0.75rem !important; }
    /* Table header */
    thead tr th { background-color: #1f3b6e !important; color: white !important; }
    /* Tight top padding */
    .block-container { padding-top: 1.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Carga de datos ────────────────────────────────────────────────────────────


@st.cache_data(show_spinner="Cargando datos…")
def get_data() -> pd.DataFrame:
    if _supabase is not None:
        try:
            return load_from_supabase(_supabase)
        except Exception as e:
            st.error(f"❌ Error al consultar Supabase: {e}")
            return pd.DataFrame()
    return load_data(DATA_DIR)


if _supabase_error:
    st.error(f"❌ Supabase no conectado: {_supabase_error}")

df = get_data()

if df.empty:
    st.error("No se encontraron datos.")
    if _supabase is None:
        st.info("Supabase no está configurado o la conexión falló. Revisa los Secrets en Streamlit Cloud.")
    else:
        st.info("Supabase conectado pero la tabla `balance_general` está vacía o inaccesible.")
    st.stop()

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏦 SIB Guatemala")
    st.caption("Superintendencia de Bancos  \nCifras en miles de quetzales")
    st.divider()

    mode = st.radio(
        "Vista",
        ["📊 Por Banco", "🔀 Comparar Bancos", "🌐 Sistema Total", "🆚 Banco vs Sistema"],
        index=0,
    )

    st.divider()

    all_banks = sorted(df["bank"].unique())

    if mode == "📊 Por Banco":
        selected_bank = st.selectbox("Banco", all_banks)
        selected_banks = [selected_bank]
    elif mode == "🔀 Comparar Bancos":
        selected_banks = st.multiselect(
            "Bancos a comparar",
            all_banks,
            default=all_banks[:5],
        )
        if not selected_banks:
            st.warning("Selecciona al menos un banco.")
            st.stop()
    elif mode == "🆚 Banco vs Sistema":
        selected_bank = st.selectbox("Banco", all_banks)
        selected_banks = [selected_bank]
    else:
        selected_banks = all_banks

    if mode != "🌐 Sistema Total":
        metric_label = st.selectbox("Métrica principal", list(METRICS.keys()), index=3)
        metric_col = METRICS[metric_label]

    st.divider()

    # Date range
    min_d, max_d = df["date"].min().date(), df["date"].max().date()
    date_range = st.date_input(
        "Rango de fechas",
        value=[min_d, max_d],
        min_value=min_d,
        max_value=max_d,
    )

    st.divider()

    # File upload → parse → insert into Supabase
    st.markdown("**Agregar nuevos datos**")
    uploaded = st.file_uploader(
        "Subir nuevo archivo .xls",
        type=["xls"],
        help="Se parseará e insertará en Supabase automáticamente.",
    )
    if uploaded is not None:
        if _supabase is None:
            st.error("Supabase no está configurado. Agrega SUPABASE_URL y SUPABASE_KEY en secrets.")
        else:
            with st.spinner("Insertando en Supabase…"):
                n = insert_file_to_supabase(_supabase, uploaded.read(), uploaded.name)
            if n > 0:
                st.success(f"✅ {n} registros nuevos insertados.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("ℹ️ Este período ya estaba en la base de datos.")

    if st.button("🔄 Recargar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    source = "Supabase ✅" if _supabase else f"archivos locales"
    st.caption(f"📦 Fuente: {source} · {df['bank'].nunique()} bancos")
    st.caption(
        f"📅 {df['date'].min().strftime('%b %Y')} → {df['date'].max().strftime('%b %Y')}"
    )

# ── Aplicar filtro de fechas ──────────────────────────────────────────────────

if len(date_range) == 2:
    d0 = pd.Timestamp(date_range[0])
    d1 = pd.Timestamp(date_range[1])
    dff = df[(df["date"] >= d0) & (df["date"] <= d1)].copy()
else:
    dff = df.copy()

last_date = dff["date"].max()

# ── Utilidades de formato ─────────────────────────────────────────────────────


def fmt_q(v) -> str:
    return f"Q{v:,.0f}" if pd.notna(v) else "—"


def fmt_pct(v) -> str:
    return f"{v:+.2f}%" if pd.notna(v) else "—"


def delta_color(v) -> str:
    if pd.isna(v):
        return "gray"
    return "green" if v >= 0 else "red"


def colored(text: str, v) -> str:
    return f"<span style='color:{delta_color(v)};font-weight:600'>{text}</span>"


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("# 🏦 SIB — Dashboard Bancario Guatemala")
st.caption(
    f"Principales Rubros de Balance General &nbsp;|&nbsp; "
    f"Último dato: **{last_date.strftime('%d de %B de %Y')}** &nbsp;|&nbsp; "
    f"Cifras en miles de quetzales"
)
st.divider()


# ═════════════════════════════════════════════════════════════════════════════
# VISTA: POR BANCO
# ═════════════════════════════════════════════════════════════════════════════

if mode == "📊 Por Banco":
    bank = selected_banks[0]
    bdf = dff[dff["bank"] == bank].sort_values("date")

    st.subheader(f"🏛 {bank}")
    st.markdown(f"*Datos desde {bdf['date'].min().strftime('%b %Y')} hasta {bdf['date'].max().strftime('%b %Y')}*")

    # ── KPI cards ─────────────────────────────────────────────────────────────
    st.markdown("#### Valores al último período")
    kpi_cols = st.columns(5)

    for i, (label, col) in enumerate(KPI_METRICS.items()):
        ch = compute_changes(dff, bank, col)
        if ch.empty:
            continue
        latest = ch.iloc[-1]
        val = latest[col]
        mom = latest["mom"]
        yoy = latest["yoy"]
        ytd = latest["ytd"]

        with kpi_cols[i]:
            st.metric(
                label=label,
                value=fmt_q(val),
                delta=f"{mom:+.1f}% MoM" if pd.notna(mom) else None,
            )
            lines = []
            if pd.notna(yoy):
                lines.append(colored(f"YoY: {fmt_pct(yoy)}", yoy))
            if pd.notna(ytd):
                lines.append(colored(f"YTD: {fmt_pct(ytd)}", ytd))
            if lines:
                st.markdown("  ".join(lines), unsafe_allow_html=True)

    st.divider()

    # ── Sparkline charts for all 5 metrics ────────────────────────────────────
    st.markdown("#### Evolución histórica")

    chart_pairs = [
        list(KPI_METRICS.items())[:2],
        list(KPI_METRICS.items())[2:4],
        [list(KPI_METRICS.items())[4]],
    ]

    for pair in chart_pairs:
        cols = st.columns(len(pair))
        for j, (label, col) in enumerate(pair):
            with cols[j]:
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=bdf["date"],
                        y=bdf[col],
                        mode="lines+markers",
                        fill="tozeroy",
                        fillcolor="rgba(31,119,180,0.10)",
                        line=dict(color="#1f6ab0", width=2),
                        marker=dict(size=5),
                        hovertemplate="%{x|%b %Y}<br><b>Q%{y:,.0f}</b><extra></extra>",
                    )
                )
                fig.update_layout(
                    title=dict(text=label, font=dict(size=13)),
                    xaxis=dict(showgrid=False, tickformat="%b %y"),
                    yaxis=dict(title="Miles de Q", showgrid=True, gridcolor="#eee"),
                    template="plotly_white",
                    height=260,
                    margin=dict(t=36, b=20, l=10, r=10),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Tabla de variaciones ──────────────────────────────────────────────────
    st.markdown("#### Tabla de variaciones")

    tab_metric_label = st.selectbox(
        "Métrica para tabla",
        list(METRICS.keys()),
        index=list(METRICS.keys()).index(metric_label),
        key="por_banco_tab_metric",
    )
    tab_col = METRICS[tab_metric_label]

    ch = compute_changes(dff, bank, tab_col)

    display = ch[["date", tab_col, "mom", "yoy", "ytd"]].copy()
    display = display.sort_values("date", ascending=False).reset_index(drop=True)

    display["Período"]          = display["date"].dt.strftime("%b %Y")
    display["Valor (miles Q)"]  = display[tab_col].apply(fmt_q)
    display["MoM %"]            = display["mom"].apply(fmt_pct)
    display["YoY %"]            = display["yoy"].apply(fmt_pct)
    display["YTD %"]            = display["ytd"].apply(fmt_pct)

    st.dataframe(
        display[["Período", "Valor (miles Q)", "MoM %", "YoY %", "YTD %"]],
        use_container_width=True,
        hide_index=True,
        height=400,
    )


# ═════════════════════════════════════════════════════════════════════════════
# VISTA: COMPARAR BANCOS
# ═════════════════════════════════════════════════════════════════════════════

elif mode == "🔀 Comparar Bancos":
    st.subheader(f"📊 {metric_label} — Comparación por banco")

    # ── KPI cards (up to 5) ───────────────────────────────────────────────────
    st.markdown("#### Último período")
    n_show = min(len(selected_banks), 5)
    kpi_cols = st.columns(n_show)
    for i, bank in enumerate(selected_banks[:n_show]):
        ch = compute_changes(dff, bank, metric_col)
        if ch.empty:
            continue
        latest = ch.iloc[-1]
        with kpi_cols[i]:
            st.metric(
                label=bank[:28],
                value=fmt_q(latest[metric_col]),
                delta=f"{latest['mom']:+.1f}% MoM" if pd.notna(latest["mom"]) else None,
            )
            yoy = latest["yoy"]
            if pd.notna(yoy):
                st.markdown(colored(f"YoY: {fmt_pct(yoy)}", yoy), unsafe_allow_html=True)

    st.divider()

    # ── Line chart ────────────────────────────────────────────────────────────
    fig_line = go.Figure()
    for i, bank in enumerate(selected_banks):
        bdf = dff[dff["bank"] == bank].sort_values("date")
        fig_line.add_trace(
            go.Scatter(
                x=bdf["date"],
                y=bdf[metric_col],
                name=bank,
                mode="lines+markers",
                line=dict(width=2, color=COLORS[i % len(COLORS)]),
                marker=dict(size=5),
                hovertemplate="%{x|%b %Y}<br><b>Q%{y:,.0f}</b><extra>%{fullData.name}</extra>",
            )
        )
    fig_line.update_layout(
        title=f"Evolución mensual — {metric_label}",
        xaxis=dict(title="Fecha", tickformat="%b %y", showgrid=False),
        yaxis=dict(title="Miles de Q", showgrid=True, gridcolor="#eee"),
        legend=dict(title="Banco", orientation="v"),
        hovermode="x unified",
        template="plotly_white",
        height=440,
    )
    st.plotly_chart(fig_line, use_container_width=True)

    # ── MoM % chart ───────────────────────────────────────────────────────────
    st.markdown("#### Variación MoM % por banco")
    fig_mom = go.Figure()
    for i, bank in enumerate(selected_banks):
        ch = compute_changes(dff, bank, metric_col)
        fig_mom.add_trace(
            go.Scatter(
                x=ch["date"],
                y=ch["mom"],
                name=bank,
                mode="lines",
                line=dict(width=1.5, color=COLORS[i % len(COLORS)]),
                hovertemplate="%{x|%b %Y}<br><b>%{y:+.2f}%</b><extra>%{fullData.name}</extra>",
            )
        )
    fig_mom.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig_mom.update_layout(
        title=f"Variación MoM (%) — {metric_label}",
        xaxis=dict(title="Fecha", tickformat="%b %y", showgrid=False),
        yaxis=dict(title="MoM %", showgrid=True, gridcolor="#eee"),
        hovermode="x unified",
        template="plotly_white",
        height=320,
    )
    st.plotly_chart(fig_mom, use_container_width=True)

    # ── Horizontal bar — último período ──────────────────────────────────────
    st.markdown(f"#### Ranking al {last_date.strftime('%b %Y')}")
    lat = dff[dff["date"] == last_date]
    lat = lat[lat["bank"].isin(selected_banks)].sort_values(metric_col, ascending=True)

    fig_bar = go.Figure(
        go.Bar(
            x=lat[metric_col],
            y=lat["bank"],
            orientation="h",
            marker=dict(color=COLORS[: len(lat)]),
            text=lat[metric_col].apply(fmt_q),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Q%{x:,.0f}<extra></extra>",
        )
    )
    fig_bar.update_layout(
        title=f"{metric_label} — {last_date.strftime('%B %Y')}",
        xaxis=dict(title="Miles de Q", showgrid=True, gridcolor="#eee"),
        template="plotly_white",
        height=max(300, 42 * len(lat) + 80),
        margin=dict(l=220),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Tabla de variaciones ──────────────────────────────────────────────────
    st.markdown("#### Variaciones por banco — último período")
    rows = []
    for bank in selected_banks:
        ch = compute_changes(dff, bank, metric_col)
        if ch.empty:
            continue
        latest = ch.iloc[-1]
        rows.append(
            {
                "Banco":            bank,
                "Valor (miles Q)":  fmt_q(latest[metric_col]),
                "MoM %":            fmt_pct(latest["mom"]),
                "YoY %":            fmt_pct(latest["yoy"]),
                "YTD %":            fmt_pct(latest["ytd"]),
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )

    # ── Tabla completa (todos los períodos, todos los bancos seleccionados) ────
    with st.expander("📋 Ver tabla completa de variaciones (todos los períodos)"):
        all_rows = []
        for bank in selected_banks:
            ch = compute_changes(dff, bank, metric_col)
            for _, row in ch.sort_values("date", ascending=False).iterrows():
                all_rows.append({
                    "Banco":           bank,
                    "Período":         row["date"].strftime("%b %Y"),
                    "Valor (miles Q)": fmt_q(row[metric_col]),
                    "MoM %":           fmt_pct(row["mom"]),
                    "YoY %":           fmt_pct(row["yoy"]),
                    "YTD %":           fmt_pct(row["ytd"]),
                })
        st.dataframe(pd.DataFrame(all_rows), use_container_width=True, hide_index=True, height=400)


# ═════════════════════════════════════════════════════════════════════════════
# VISTA: SISTEMA TOTAL
# ═════════════════════════════════════════════════════════════════════════════

elif mode == "🌐 Sistema Total":
    st.subheader("🌐 Sistema Bancario Total — Todos los bancos")

    total_df = compute_system_totals(dff)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    st.markdown("#### Último período — Sistema consolidado")
    kpi_cols = st.columns(5)
    for i, (label, col) in enumerate(KPI_METRICS.items()):
        latest = total_df.iloc[-1]
        mom = latest.get(f"{col}_mom")
        with kpi_cols[i]:
            st.metric(
                label=label,
                value=fmt_q(latest[col]),
                delta=f"{mom:+.1f}% MoM" if pd.notna(mom) else None,
            )
            yoy = latest.get(f"{col}_yoy")
            if pd.notna(yoy):
                st.markdown(colored(f"YoY: {fmt_pct(yoy)}", yoy), unsafe_allow_html=True)

    st.divider()

    # ── Multi-metric line chart ───────────────────────────────────────────────
    st.markdown("#### Evolución del sistema")

    fig_sys = go.Figure()
    for i, (label, col) in enumerate(KPI_METRICS.items()):
        fig_sys.add_trace(
            go.Scatter(
                x=total_df["date"],
                y=total_df[col],
                name=label,
                mode="lines",
                line=dict(width=2, color=COLORS[i]),
                hovertemplate="%{x|%b %Y}<br><b>Q%{y:,.0f}</b><extra>%{fullData.name}</extra>",
            )
        )
    fig_sys.update_layout(
        title="Sistema bancario — todos los rubros",
        xaxis=dict(title="Fecha", tickformat="%b %y", showgrid=False),
        yaxis=dict(title="Miles de Q", showgrid=True, gridcolor="#eee"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        template="plotly_white",
        height=460,
    )
    st.plotly_chart(fig_sys, use_container_width=True)

    # ── Stacked area — participación bancaria ─────────────────────────────────
    st.markdown("#### Participación por banco — Total Activo Neto")

    pivot = (
        dff.pivot_table(index="date", columns="bank", values="total_activo_neto", aggfunc="sum")
        .fillna(0)
    )

    fig_stack = go.Figure()
    for j, bank in enumerate(pivot.columns):
        fig_stack.add_trace(
            go.Scatter(
                x=pivot.index,
                y=pivot[bank],
                name=bank,
                mode="lines",
                stackgroup="one",
                line=dict(width=0.5),
                fillcolor=COLORS[j % len(COLORS)],
                hovertemplate="%{x|%b %Y}<br><b>Q%{y:,.0f}</b><extra>%{fullData.name}</extra>",
            )
        )
    fig_stack.update_layout(
        title="Activo Neto por banco — área apilada",
        xaxis=dict(title="Fecha", tickformat="%b %y", showgrid=False),
        yaxis=dict(title="Miles de Q", showgrid=True, gridcolor="#eee"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.4, font=dict(size=10)),
        template="plotly_white",
        height=480,
    )
    st.plotly_chart(fig_stack, use_container_width=True)

    # ── Market share % (latest) ───────────────────────────────────────────────
    st.markdown(f"#### Cuota de mercado — {last_date.strftime('%B %Y')}")
    lat = dff[dff["date"] == last_date].copy()
    total_act = lat["total_activo_neto"].sum()
    lat["share"] = lat["total_activo_neto"] / total_act * 100
    lat = lat.sort_values("share", ascending=False)

    fig_pie = go.Figure(
        go.Pie(
            labels=lat["bank"],
            values=lat["total_activo_neto"],
            hole=0.40,
            hovertemplate="<b>%{label}</b><br>Q%{value:,.0f}<br>%{percent}<extra></extra>",
            textinfo="percent+label",
            textfont_size=11,
        )
    )
    fig_pie.update_layout(
        title=f"Participación en Total Activo Neto — {last_date.strftime('%B %Y')}",
        template="plotly_white",
        height=500,
        showlegend=False,
    )
    st.plotly_chart(fig_pie, use_container_width=True)

    # ── Sistema total table ───────────────────────────────────────────────────
    st.markdown("#### Tabla resumen del sistema")
    display = total_df[["date"] + list(KPI_METRICS.values())].copy()
    display = display.sort_values("date", ascending=False).reset_index(drop=True)
    display["Período"] = display["date"].dt.strftime("%b %Y")
    for label, col in KPI_METRICS.items():
        display[label] = display[col].apply(fmt_q)
    st.dataframe(
        display[["Período"] + list(KPI_METRICS.keys())],
        use_container_width=True,
        hide_index=True,
        height=420,
    )


# ═════════════════════════════════════════════════════════════════════════════
# VISTA: BANCO VS SISTEMA
# ═════════════════════════════════════════════════════════════════════════════

elif mode == "🆚 Banco vs Sistema":
    bank = selected_banks[0]
    st.subheader(f"🆚 {bank} — vs Sistema")
    st.markdown(
        f"Participación y dinámica de **{bank}** respecto al total del sistema bancario."
    )

    bvs = compute_bank_vs_system(dff, bank)

    if bvs.empty:
        st.warning("No hay datos suficientes para este banco.")
        st.stop()

    # ── Section 1: Share % KPI cards (5 key metrics, latest period) ───────────
    st.markdown("#### Participación en el sistema — último período")
    kpi_cols = st.columns(5)
    for i, (label, col) in enumerate(KPI_METRICS.items()):
        sub = bvs[bvs["metric"] == col].sort_values("date")
        if sub.empty:
            continue
        latest   = sub.iloc[-1]
        prior    = sub.iloc[-2] if len(sub) >= 2 else None
        share    = latest["share_pct"]
        delta_share = (share - prior["share_pct"]) if prior is not None else None
        with kpi_cols[i]:
            st.metric(
                label=label,
                value=f"{share:.2f}%",
                delta=f"{delta_share:+.2f}pp" if delta_share is not None else None,
                help="Participación del banco en el total del sistema (porcentaje)",
            )
            bank_val   = latest["bank_value"]
            system_val = latest["system_total"]
            st.caption(f"Banco: {fmt_q(bank_val)}  \nSistema: {fmt_q(system_val)}")

    st.divider()

    # ── Section 2: Market share evolution (line chart) ────────────────────────
    st.markdown("#### Evolución de participación en el sistema")
    sub = bvs[bvs["metric"] == metric_col].sort_values("date")

    fig_share = go.Figure()
    fig_share.add_trace(
        go.Scatter(
            x=sub["date"],
            y=sub["share_pct"],
            name=bank,
            mode="lines+markers",
            fill="tozeroy",
            fillcolor="rgba(31,119,180,0.10)",
            line=dict(color="#1f6ab0", width=2),
            marker=dict(size=5),
            hovertemplate="%{x|%b %Y}<br><b>%{y:.2f}%</b><extra></extra>",
        )
    )
    # Reference: system average share (100 / number of banks)
    n_banks = dff["bank"].nunique()
    avg_share = 100 / n_banks
    fig_share.add_hline(
        y=avg_share,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"Promedio sistema ({avg_share:.1f}%)",
        annotation_position="top right",
    )
    fig_share.update_layout(
        title=f"Participación % en {metric_label}",
        xaxis=dict(title="Fecha", tickformat="%b %y", showgrid=False),
        yaxis=dict(title="% del sistema", showgrid=True, gridcolor="#eee"),
        template="plotly_white",
        height=380,
        showlegend=False,
    )
    st.plotly_chart(fig_share, use_container_width=True)

    st.divider()

    # ── Section 3: Growth rate comparison — bank MoM% vs system MoM% ──────────
    st.markdown("#### Crecimiento mensual: banco vs sistema")
    sub12 = sub.tail(13).copy()  # last 12 months of changes

    fig_growth = go.Figure()
    fig_growth.add_trace(
        go.Bar(
            x=sub12["date"],
            y=sub12["mom_bank"],
            name=bank,
            marker_color="#1f6ab0",
            opacity=0.85,
            hovertemplate="%{x|%b %Y}<br><b>%{y:+.2f}%</b><extra>" + bank + "</extra>",
        )
    )
    fig_growth.add_trace(
        go.Bar(
            x=sub12["date"],
            y=sub12["mom_system"],
            name="Sistema",
            marker_color="#f28e2b",
            opacity=0.85,
            hovertemplate="%{x|%b %Y}<br><b>%{y:+.2f}%</b><extra>Sistema</extra>",
        )
    )
    fig_growth.add_hline(y=0, line_color="gray", line_width=1)
    fig_growth.update_layout(
        title=f"MoM % — {metric_label}",
        barmode="group",
        xaxis=dict(title="Fecha", tickformat="%b %y", showgrid=False),
        yaxis=dict(title="MoM %", showgrid=True, gridcolor="#eee"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        template="plotly_white",
        height=360,
    )
    st.plotly_chart(fig_growth, use_container_width=True)

    st.divider()

    # ── Section 4: All-metrics snapshot table (latest period) ─────────────────
    st.markdown("#### Todos los rubros — último período")
    metric_label_map = {v: k for k, v in METRICS.items()}
    latest_rows = []
    for col in list(METRICS.values()):
        sub_col = bvs[bvs["metric"] == col].sort_values("date")
        if sub_col.empty:
            continue
        row = sub_col.iloc[-1]
        latest_rows.append({
            "Rubro":            metric_label_map.get(col, col),
            "Banco (miles Q)":  fmt_q(row["bank_value"]),
            "Sistema (miles Q)": fmt_q(row["system_total"]),
            "Participación %":  f"{row['share_pct']:.2f}%",
            "MoM Banco":        fmt_pct(row["mom_bank"]),
            "MoM Sistema":      fmt_pct(row["mom_system"]),
        })
    st.dataframe(
        pd.DataFrame(latest_rows),
        use_container_width=True,
        hide_index=True,
    )
