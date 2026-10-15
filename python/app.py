"""OpsPulse em Streamlit.

Rodar:  streamlit run python/app.py
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import opspulse_core as core

AMOSTRA = Path(__file__).resolve().parent.parent / "data" / "exemplo_producao.csv"
CORES = {"verde": "#1d8049", "amarelo": "#b77d00", "vermelho": "#c2352b"}
ICONES = {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}

st.set_page_config(page_title="OpsPulse", page_icon="🚦", layout="wide")

# ---------- Barra lateral: dados e limites ----------
with st.sidebar:
    st.header("Dados")
    arquivo = st.file_uploader("CSV de produção hora a hora", type=["csv", "txt"])
    st.caption("Colunas: data, hora, area, volume, meta e headcount (opcional). Aceita vírgula ou ponto e vírgula.")
    st.header("Limites do farol")
    verde = st.slider("Verde a partir de (% da meta)", 50, 120, 95)
    amarelo = st.slider("Amarelo a partir de (% da meta)", 40, 115, 85)
    if amarelo >= verde:
        st.error("O limite do amarelo precisa ser menor que o do verde.")
        st.stop()
    limites = {"verde": verde / 100, "amarelo": amarelo / 100}


@st.cache_data
def carregar(conteudo: bytes | None) -> pd.DataFrame:
    if conteudo is None:
        return core.ler_csv(str(AMOSTRA))
    return core.ler_csv(conteudo.decode("utf-8-sig"))


try:
    df = carregar(arquivo.getvalue() if arquivo else None)
except core.ErroDeArquivo as e:
    st.error(f"Não foi possível ler o arquivo. {e}")
    st.stop()

# ---------- Cabeçalho e filtros ----------
st.title("OpsPulse")
st.caption("Farol operacional hora a hora" + ("" if arquivo else " · usando dados fictícios de exemplo"))

datas = sorted(df["data_op"].unique(), reverse=True)
c1, c2, _ = st.columns([1, 1, 2])
data_op = c1.selectbox("Data operacional", datas, format_func=lambda d: pd.Timestamp(d).strftime("%d/%m/%Y"))
turnos = [t for t in core.TURNOS if t in set(df.loc[df["data_op"] == data_op, "turno"])]
turno = c2.radio("Turno", turnos, index=len(turnos) - 1, horizontal=True)

res = core.resumir(df, data_op, turno, limites)
lista = core.alertas(res, limites)
t = res.total
inicio = core.TURNOS[turno]

status = (
    f"🟦 Em andamento · até {res.ultima_hora:02d}h59 · {res.horas_com_dado} de {core.HORAS_TURNO} h"
    if res.em_andamento else f"Turno fechado · {res.horas_com_dado} de {core.HORAS_TURNO} h"
)
st.subheader(f"Turno {turno} · {inicio:02d}h–{(inicio + 8) % 24:02d}h")
st.caption(status)

k = st.columns(5)
k[0].metric("Realizado", core._fmt(t["realizado"]))
k[1].metric("Meta acumulada", core._fmt(t["meta_acum"]), help=f"Meta do turno: {core._fmt(t['meta_turno'])}")
k[2].metric("Atingimento", core._pct(t["atingimento"]), f"{core._fmt(t['realizado'] - t['meta_acum'])} vs meta")
k[3].metric("Projeção de fechamento" if res.em_andamento else "Fechamento",
            core._fmt(t["projecao"]), f"{core._pct(t['proj_pct'])} da meta do turno", delta_color="off")
k[4].metric("UPH", f"{t['uph']:.1f}".replace(".", ",") if pd.notna(t["uph"]) else "—")

# ---------- Farol + gráfico | alertas + resumo ----------
esq, dir_ = st.columns([1.7, 1])
with esq:
    st.markdown("#### Farol por área")
    tabela = res.areas.assign(
        Farol=res.areas["farol"].map(ICONES),
        Área=res.areas["area"],
        Realizado=res.areas["realizado"].round().astype(int),
        **{"Meta acum.": res.areas["meta_acum"].round().astype(int)},
        Atingimento=res.areas["atingimento"] * 100,
        Projeção=res.areas["projecao"].round().astype(int),
        UPH=res.areas["uph"].round(1),
    )[["Farol", "Área", "Realizado", "Meta acum.", "Atingimento", "Projeção", "UPH"]]
    st.dataframe(
        tabela, hide_index=True, width="stretch",
        column_config={"Atingimento": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=120)},
    )

    st.markdown("#### Hora a hora")
    g1, g2 = st.columns([1, 1])
    modo = g1.radio("Visão", ["Por hora", "Acumulado"], horizontal=True, label_visibility="collapsed")
    area = g2.selectbox("Área", ["Todas as áreas"] + list(res.areas["area"]), label_visibility="collapsed")
    hh = res.hora_a_hora if area == "Todas as áreas" else res.hora_a_hora[res.hora_a_hora["area"] == area]
    serie = hh.groupby("pos")[["volume", "meta"]].sum().reindex(range(core.HORAS_TURNO))
    sel = res.areas if area == "Todas as áreas" else res.areas[res.areas["area"] == area]
    ritmo = sel["ritmo"].sum()
    meta_media = serie["meta"].mean()
    serie["meta"] = serie["meta"].fillna(meta_media)
    rotulos = [f"{(inicio + i) % 24:02d}h" for i in range(core.HORAS_TURNO)]

    fig = go.Figure()
    if modo == "Por hora":
        cores = [CORES[core.farol(v / m, limites)] if pd.notna(v) else "rgba(0,0,0,0)" for v, m in zip(serie["volume"], serie["meta"])]
        fig.add_bar(x=rotulos, y=serie["volume"], marker_color=cores, name="Realizado")
        if res.em_andamento:
            proj = [ritmo if pd.isna(v) else None for v in serie["volume"]]
            fig.add_bar(x=rotulos, y=proj, name="Projeção", marker=dict(color="rgba(0,0,0,0)", line=dict(color="#5b6974", width=1.5)), marker_pattern_shape="/")
        fig.add_scatter(x=rotulos, y=serie["meta"], mode="lines", line=dict(dash="dash", shape="hvh", color="#15222c"), name="Meta")
        fig.update_layout(barmode="overlay")
    else:
        real = serie["volume"].cumsum()
        fig.add_scatter(x=rotulos, y=real, mode="lines+markers", fill="tozeroy", name="Realizado acumulado", line=dict(color="#2c4f80"))
        fig.add_scatter(x=rotulos, y=serie["meta"].cumsum(), mode="lines", line=dict(dash="dash", color="#15222c"), name="Meta acumulada")
        if res.em_andamento:
            ult = serie["volume"].last_valid_index()
            xs = rotulos[ult:]
            ys = [real[ult] + ritmo * i for i in range(len(xs))]
            fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(dash="dot", color="#2c4f80"), name="Projeção")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")

with dir_:
    st.markdown(f"#### Alertas · {len(lista)}")
    if not lista:
        st.success("Nenhuma área fora do limite neste turno.")
    for a in lista:
        (st.error if a["sev"] == "critico" else st.warning)(a["texto"])

    st.markdown("#### Resumo para o grupo")
    st.code(core.resumo_texto(res, lista), language=None)
    st.caption("Use o botão de copiar no canto do bloco e cole no WhatsApp ou Teams.")
