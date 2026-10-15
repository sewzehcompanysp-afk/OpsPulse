"""Garante que a versão web (núcleo JavaScript em web/index.template.html) calcula
os mesmos números, alertas e resumo que o núcleo Python.

O teste extrai o bloco <script id="opspulse-core"> do template, roda esse código
no Node com o mesmo CSV e compara, turno a turno, com opspulse_core.py.
"""
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import opspulse_core as core

RAIZ = Path(__file__).resolve().parents[2]
CSV_EXEMPLO = RAIZ / "data" / "exemplo_producao.csv"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js não encontrado")

# A versão web usa ok/warn/crit; a Python usa verde/amarelo/vermelho.
FAROL = {"ok": "verde", "warn": "amarelo", "crit": "vermelho"}
SEV = {"crit": "critico", "warn": "atencao"}

# Roda o núcleo web sobre um CSV e devolve, para cada turno do arquivo,
# indicadores por área, total, alertas e o texto do resumo.
HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const { core, csv } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(core, ctx);
const O = ctx.OpsPulse;
const lim = { verde: 0.95, amarelo: 0.85 };
const parsed = O.parseCSV(csv);
if (parsed.erro) { console.log(JSON.stringify({ erro: parsed.erro })); process.exit(0); }
const turnos = [...new Set(parsed.rows.map((r) => r.dataOp + "|" + r.turno))].sort();
const out = { ignoradas: parsed.ignoradas, linhas: parsed.rows.length, turnos: {} };
for (const chave of turnos) {
  const [dataOp, turno] = chave.split("|");
  const res = O.resumir(parsed.rows, dataOp, turno, lim);
  const lista = O.alertas(res, lim);
  out.turnos[chave] = {
    n: res.n,
    emAndamento: res.emAndamento,
    areas: res.areas.map((a) => ({
      area: a.area, horas: a.horas, realizado: a.realizado, metaAcum: a.metaAcum,
      metaTurno: a.metaTurno, projecao: a.projecao, ating: a.ating, projPct: a.projPct,
      uph: a.uph, farol: a.farol,
    })),
    total: res.total,
    alertas: lista.filter((x) => x.sev !== "info").map((x) => ({ sev: x.sev, texto: x.texto })),
    resumo: O.resumoTexto(res, lista),
  };
}
console.log(JSON.stringify(out));
"""


def _nucleo_web() -> str:
    template = (RAIZ / "web" / "index.template.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="opspulse-core">(.*?)</script>', template, re.S)
    assert m, "bloco <script id=\"opspulse-core\"> não encontrado no template"
    return m.group(1)


def rodar_web(csv_texto: str) -> dict:
    entrada = json.dumps({"core": _nucleo_web(), "csv": csv_texto})
    proc = subprocess.run(
        ["node", "-e", HARNESS], input=entrada, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return json.loads(proc.stdout)


def rodar_python(csv_texto: str) -> dict:
    df = core.ler_csv(csv_texto)
    out = {"ignoradas": df.attrs["ignoradas"], "linhas": len(df), "turnos": {}}
    for data_op, turno in sorted(set(zip(df["data_op"], df["turno"]))):
        res = core.resumir(df, data_op, turno)
        out["turnos"][f"{data_op}|{turno}"] = (res, core.alertas(res), )
    return out


def _vazio(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _igual(web, py) -> bool:
    if _vazio(web) or _vazio(py):
        return _vazio(web) and _vazio(py)
    return web == pytest.approx(py, rel=1e-9, abs=1e-9)


def comparar(csv_texto: str) -> None:
    web = rodar_web(csv_texto)
    py = rodar_python(csv_texto)

    assert web["linhas"] == py["linhas"], "quantidade de linhas válidas"
    assert web["ignoradas"] == py["ignoradas"], "quantidade de linhas ignoradas"
    assert set(web["turnos"]) == set(py["turnos"]), "turnos encontrados no arquivo"

    campos = [  # (web, python)
        ("horas", "horas"), ("realizado", "realizado"), ("metaAcum", "meta_acum"),
        ("metaTurno", "meta_turno"), ("projecao", "projecao"), ("ating", "atingimento"),
        ("projPct", "proj_pct"), ("uph", "uph"),
    ]
    for chave, w in web["turnos"].items():
        res, alertas_py = py["turnos"][chave]
        assert w["n"] == res.horas_com_dado, f"{chave}: horas com dado"
        assert w["emAndamento"] == res.em_andamento, f"{chave}: turno em andamento"

        areas_py = res.areas.to_dict("records")
        assert [a["area"] for a in w["areas"]] == [a["area"] for a in areas_py], f"{chave}: áreas e ordem"
        for aw, ap in zip(w["areas"], areas_py):
            for cw, cp in campos:
                assert _igual(aw[cw], ap[cp]), f"{chave} · {aw['area']} · {cp}: web={aw[cw]} python={ap[cp]}"
            assert FAROL[aw["farol"]] == ap["farol"], f"{chave} · {aw['area']} · farol"

        t = res.total
        for cw, cp in [("realizado", "realizado"), ("metaAcum", "meta_acum"), ("metaTurno", "meta_turno"),
                       ("projecao", "projecao"), ("ating", "atingimento"), ("projPct", "proj_pct"), ("uph", "uph")]:
            assert _igual(w["total"][cw], t[cp]), f"{chave} · total · {cp}: web={w['total'][cw]} python={t[cp]}"
        assert FAROL[w["total"]["farol"]] == t["farol"], f"{chave} · total · farol"

        assert [(SEV[a["sev"]], a["texto"]) for a in w["alertas"]] == [(a["sev"], a["texto"]) for a in alertas_py], \
            f"{chave}: alertas"
        assert w["resumo"] == core.resumo_texto(res, alertas_py), f"{chave}: texto do resumo"


def test_base_de_exemplo_inteira():
    """Todos os turnos da base de exemplo: 8 dias x 3 turnos, com o último em andamento."""
    comparar(CSV_EXEMPLO.read_text(encoding="utf-8"))


# Arquivos "do mundo real": cada um exercita um caminho diferente da leitura.
VARIACOES = {
    "ponto_e_virgula_data_br_milhar": (
        "Data;Horário;Setor;Realizado;Planejado;Pessoas\n"
        "15/10/2026;14:00;Picking;1.234,5;1.300;12\n"
        "15/10/2026;15:00;Picking;1.180;1.300;12\n"
        "15/10/2026;14:00;Expedição;980;1.200;10\n"
        "15/10/2026;15:00;Expedição;850;1.200;10\n"
        "15/10/2026;16:00;Expedição;700;1.200;10\n"
    ),
    "tabulacao_ingles_sem_headcount": (
        "date\thour\tarea\tvolume\ttarget\n"
        "2026-10-15\t6\tPacking\t1500\t1600\n"
        "2026-10-15\t7\tPacking\t1650\t1600\n"
        "2026-10-15\t8\tPacking\t1100\t1600\n"
    ),
    "turno_da_madrugada_vira_o_dia": (
        "data,hora,area,volume,meta,headcount\n"
        "2026-10-15,22,Recebimento,900,1000,10\n"
        "2026-10-15,23,Recebimento,950,1000,10\n"
        "2026-10-16,0,Recebimento,800,1000,10\n"
        "2026-10-16,1,Recebimento,780,1000,10\n"
        "2026-10-16,2,Recebimento,500,1000,10\n"
    ),
    "hora_junto_da_data_e_linhas_invalidas": (
        "datahora,area,qtd,meta\n"
        "2026-10-15 14:00,Picking,1700,1800\n"
        "2026-10-15 15:00,Picking,1750,1800\n"
        "2026-10-15 16:00,Picking,,1800\n"
        "data ruim,Picking,1000,1800\n"
        "2026-10-15 17:00,,1000,1800\n"
    ),
    "projecao_com_meia_unidade": (
        # realizado 3.000 + ritmo 1.000,5 x 5 h = 8.002,5. Arredondar "para o par" daria 8.002;
        # "para cima" (como o navegador faz) dá 8.003. O resumo precisa mostrar o mesmo número.
        "data,hora,area,volume,meta\n"
        "2026-10-15,14,Picking,999,1000\n"
        "2026-10-15,15,Picking,1000,1000\n"
        "2026-10-15,16,Picking,1001,1000\n"
    ),
}


@pytest.mark.parametrize("nome", VARIACOES)
def test_variacoes_de_arquivo(nome):
    comparar(VARIACOES[nome])
