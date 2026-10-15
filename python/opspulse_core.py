"""Núcleo de cálculo do OpsPulse em Python (pandas).

Mesmas regras da versão web (web/index.template.html) e da versão SQL (sql/kpis.sql):

* Turnos T1 06h-14h, T2 14h-22h, T3 22h-06h. Horas de 00h a 05h pertencem ao T3
  da data operacional anterior.
* Atingimento = realizado / meta acumulada das horas com dado.
* Meta do turno = meta acumulada + meta média por hora x horas que faltam.
* Projeção = realizado + média das últimas 2 horas x horas que faltam.
* UPH = realizado / soma do headcount (pessoas-hora).
* Farol: verde >= 95% da meta acumulada, amarelo >= 85%, vermelho abaixo disso.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

TURNOS = {"T1": 6, "T2": 14, "T3": 22}  # hora de início
HORAS_TURNO = 8
LIMITES_PADRAO = {"verde": 0.95, "amarelo": 0.85}

ALIASES = {
    "data": ["data", "date", "dia", "dataoperacao", "datahora"],
    "hora": ["hora", "hour", "horario", "faixa", "faixahoraria"],
    "area": ["area", "setor", "processo", "etapa", "operacao"],
    "volume": ["volume", "realizado", "qtd", "quantidade", "produzido", "unidades"],
    "meta": ["meta", "target", "objetivo", "planejado"],
    "headcount": ["headcount", "hc", "pessoas", "colaboradores", "operadores"],
}
OBRIGATORIAS = ["data", "area", "volume", "meta"]


class ErroDeArquivo(ValueError):
    """O arquivo não tem o formato esperado."""


def _norm(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def _numero(serie: pd.Series) -> pd.Series:
    def conv(v):
        s = re.sub(r"\s", "", str(v))
        if s in ("", "nan", "None"):
            return float("nan")
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return float("nan")

    return serie.map(conv)


def turno_da_hora(hora: int) -> tuple[str, int]:
    """Devolve (turno, posição da hora dentro do turno, de 0 a 7)."""
    for turno, inicio in TURNOS.items():
        pos = (hora - inicio) % 24
        if pos < HORAS_TURNO:
            return turno, pos
    raise ValueError(f"Hora fora dos turnos: {hora}")


def ler_csv(origem) -> pd.DataFrame:
    """Lê um CSV (caminho, texto ou arquivo enviado) e devolve a base normalizada.

    Colunas de saída: data_op, hora, turno, pos, area, volume, meta, headcount.
    """
    if hasattr(origem, "read"):
        conteudo = origem.read()
        texto = conteudo.decode("utf-8-sig") if isinstance(conteudo, bytes) else conteudo
    elif isinstance(origem, str) and "\n" in origem:
        texto = origem
    else:
        with open(origem, encoding="utf-8-sig") as f:
            texto = f.read()
    texto = texto.lstrip("﻿")
    cab = texto.splitlines()[0] if texto.strip() else ""
    sep = max([";", "\t", ","], key=cab.count)
    bruto = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, skipinitialspace=True)

    mapa: dict[str, str] = {}
    for col in bruto.columns:
        chave = _norm(col)
        for campo, lista in ALIASES.items():
            if campo not in mapa and chave in lista:
                mapa[campo] = col
    faltam = [c for c in OBRIGATORIAS if c not in mapa]
    if faltam:
        raise ErroDeArquivo(
            f"Faltam as colunas: {', '.join(faltam)}. Colunas encontradas: {', '.join(bruto.columns)}."
        )

    df = pd.DataFrame()
    datas = bruto[mapa["data"]].astype(str).str.strip()
    iso = pd.to_datetime(datas.str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    br = pd.to_datetime(datas.str.extract(r"^(\d{1,2}/\d{1,2}/\d{4})")[0], format="%d/%m/%Y", errors="coerce")
    df["data_cal"] = iso.fillna(br)
    if "hora" in mapa:
        df["hora"] = pd.to_numeric(bruto[mapa["hora"]].astype(str).str.split(":").str[0], errors="coerce")
    else:
        df["hora"] = pd.to_numeric(datas.str.extract(r"[ T](\d{1,2})")[0], errors="coerce")
    df["area"] = bruto[mapa["area"]].astype(str).str.strip()
    df["volume"] = _numero(bruto[mapa["volume"]])
    df["meta"] = _numero(bruto[mapa["meta"]])
    df["headcount"] = _numero(bruto[mapa["headcount"]]) if "headcount" in mapa else float("nan")

    validas = (
        df["data_cal"].notna() & df["hora"].between(0, 23) & df["area"].ne("")
        & df["volume"].notna() & df["meta"].notna()
    )
    df = df[validas].copy()
    if df.empty:
        raise ErroDeArquivo("Nenhuma linha válida. Confira datas, horas e números.")
    df["hora"] = df["hora"].astype(int)
    tp = df["hora"].map(turno_da_hora)
    df["turno"] = tp.str[0]
    df["pos"] = tp.str[1]
    vira = (df["turno"] == "T3") & (df["hora"] < 6)
    df["data_op"] = (df["data_cal"] - pd.to_timedelta(vira.astype(int), unit="D")).dt.date.astype(str)
    df.attrs["ignoradas"] = int((~validas).sum())
    return df[["data_op", "hora", "turno", "pos", "area", "volume", "meta", "headcount"]].reset_index(drop=True)


def farol(atingimento: float, limites: dict = LIMITES_PADRAO) -> str:
    if pd.isna(atingimento):
        return "amarelo"
    if atingimento >= limites["verde"]:
        return "verde"
    return "amarelo" if atingimento >= limites["amarelo"] else "vermelho"


@dataclass
class Resumo:
    data_op: str
    turno: str
    horas_com_dado: int
    areas: pd.DataFrame       # uma linha por área
    hora_a_hora: pd.DataFrame  # area x pos
    total: dict

    @property
    def em_andamento(self) -> bool:
        return 0 < self.horas_com_dado < HORAS_TURNO

    @property
    def ultima_hora(self) -> int | None:
        if self.hora_a_hora.empty:
            return None
        return (TURNOS[self.turno] + int(self.hora_a_hora["pos"].max())) % 24


def resumir(df: pd.DataFrame, data_op: str, turno: str, limites: dict = LIMITES_PADRAO) -> Resumo:
    """Calcula os indicadores de um turno."""
    t = df[(df["data_op"] == data_op) & (df["turno"] == turno)]
    hh = (
        t.groupby(["area", "pos"], sort=False)
        .agg(volume=("volume", "sum"), meta=("meta", "sum"), headcount=("headcount", "sum"))
        .reset_index()
        .sort_values(["area", "pos"], kind="stable")
    )
    linhas = []
    for area, g in hh.groupby("area", sort=False):
        n = len(g)
        realizado = g["volume"].sum()
        meta_acum = g["meta"].sum()
        faltam = HORAS_TURNO - n
        ritmo = g["volume"].tail(2).mean()
        hc = g["headcount"].sum()
        anteriores = g["volume"].iloc[:-1]
        linhas.append({
            "area": area,
            "horas": n,
            "realizado": realizado,
            "meta_acum": meta_acum,
            "atingimento": realizado / meta_acum if meta_acum else float("nan"),
            "meta_turno": meta_acum + (meta_acum / n) * faltam,
            "ritmo": ritmo,
            "projecao": realizado + ritmo * faltam,
            "uph": realizado / hc if hc else float("nan"),
            "ultima_hora": g["volume"].iloc[-1],
            "media_anteriores": anteriores.mean() if len(anteriores) else float("nan"),
        })
    areas = pd.DataFrame(linhas)
    # mantém a ordem em que as áreas aparecem no arquivo
    ordem = list(dict.fromkeys(t["area"]))
    if not areas.empty:
        areas = areas.set_index("area").loc[ordem].reset_index()
        areas["proj_pct"] = areas["projecao"] / areas["meta_turno"]
        areas["farol"] = areas["atingimento"].map(lambda x: farol(x, limites))

    total = {}
    if not areas.empty:
        hc_total = (areas["realizado"] / areas["uph"]).where(areas["uph"].notna()).sum()
        total = {
            "realizado": areas["realizado"].sum(),
            "meta_acum": areas["meta_acum"].sum(),
            "meta_turno": areas["meta_turno"].sum(),
            "projecao": areas["projecao"].sum(),
            "uph": areas["realizado"].sum() / hc_total if hc_total else float("nan"),
        }
        total["atingimento"] = total["realizado"] / total["meta_acum"]
        total["proj_pct"] = total["projecao"] / total["meta_turno"]
        total["farol"] = farol(total["atingimento"], limites)
    return Resumo(data_op, turno, int(t["pos"].nunique()), areas, hh, total)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def _fmt(x: float) -> str:
    return f"{round(x):,}".replace(",", ".")


def alertas(res: Resumo, limites: dict = LIMITES_PADRAO) -> list[dict]:
    """Lista de alertas, do mais grave para o menos grave."""
    out = []
    for a in res.areas.to_dict("records"):
        if a["farol"] == "vermelho":
            out.append({"sev": "critico", "area": a["area"], "texto": f"{a['area']} está em {_pct(a['atingimento'])} da meta acumulada."})
        elif a["farol"] == "amarelo":
            out.append({"sev": "atencao", "area": a["area"], "texto": f"{a['area']} está em {_pct(a['atingimento'])} da meta acumulada."})
        if res.em_andamento and a["proj_pct"] < limites["verde"]:
            sev = "critico" if a["proj_pct"] < limites["amarelo"] else "atencao"
            out.append({"sev": sev, "area": a["area"], "texto": f"{a['area']} deve fechar o turno com {_pct(a['proj_pct'])} da meta."})
        media = a["media_anteriores"]
        if a["horas"] >= 3 and pd.notna(media) and media > 0 and a["ultima_hora"] < media * 0.85:
            out.append({"sev": "atencao", "area": a["area"], "texto": f"{a['area']} caiu {_pct(1 - a['ultima_hora'] / media)} na última hora."})
    ordem = {"critico": 0, "atencao": 1}
    return sorted(out, key=lambda x: ordem[x["sev"]])


def resumo_texto(res: Resumo, lista: list[dict]) -> str:
    """Texto curto para colar no grupo da operação."""
    icone = {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}
    y, m, d = res.data_op.split("-")
    t = res.total
    linhas = [f"*OpsPulse · {res.turno} · {d}/{m}/{y}*"]
    if res.em_andamento:
        linhas.append(f"Atualizado até {res.ultima_hora:02d}h59 ({res.horas_com_dado} de {HORAS_TURNO} h)")
    else:
        linhas.append(f"Turno fechado ({res.horas_com_dado} de {HORAS_TURNO} h)")
    linhas += ["", f"{icone[t['farol']]} *Total:* {_fmt(t['realizado'])} / {_fmt(t['meta_acum'])} ({t['atingimento'] * 100:.0f}%)"]
    if res.em_andamento:
        linhas.append(f"Projeção de fechamento: {_fmt(t['projecao'])} de {_fmt(t['meta_turno'])} ({t['proj_pct'] * 100:.0f}%)")
    linhas.append("")
    for a in res.areas.to_dict("records"):
        linhas.append(f"{icone[a['farol']]} {a['area']}: {_fmt(a['realizado'])} / {_fmt(a['meta_acum'])} ({a['atingimento'] * 100:.0f}%)")
    if lista:
        linhas += ["", "*Pontos de atenção*"] + [f"• {x['texto']}" for x in lista[:4]]
    return "\n".join(linhas)
