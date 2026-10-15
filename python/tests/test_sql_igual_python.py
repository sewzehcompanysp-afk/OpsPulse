"""Garante que a versão SQL (sql/kpis.sql) calcula os mesmos números que o núcleo Python."""
import csv
import sqlite3
from pathlib import Path

import pytest

import opspulse_core as core

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def db():
    con = sqlite3.connect(":memory:")
    con.executescript((RAIZ / "sql" / "schema.sql").read_text(encoding="utf-8"))
    with open(RAIZ / "data" / "exemplo_producao.csv", encoding="utf-8") as f:
        linhas = list(csv.reader(f))[1:]
    con.executemany("INSERT INTO producao VALUES (?,?,?,?,?,?)", linhas)
    visoes = (RAIZ / "sql" / "kpis.sql").read_text(encoding="utf-8").split("-- Consulta de exemplo")[0]
    con.executescript(visoes)
    return con


@pytest.mark.parametrize("data_op,turno", [("2026-10-15", "T2"), ("2026-10-15", "T1"), ("2026-10-14", "T3")])
def test_mesmos_numeros(db, data_op, turno):
    res = core.resumir(core.ler_csv(str(RAIZ / "data" / "exemplo_producao.csv")), data_op, turno)
    py = res.areas.set_index("area")
    sql = db.execute(
        "SELECT area, realizado, meta_acum, projecao, meta_turno, uph, farol FROM v_area_turno WHERE data_op=? AND turno=?",
        (data_op, turno),
    ).fetchall()
    assert len(sql) == len(py)
    for area, realizado, meta_acum, projecao, meta_turno, uph, farol in sql:
        a = py.loc[area]
        assert realizado == pytest.approx(a["realizado"])
        assert meta_acum == pytest.approx(a["meta_acum"])
        assert projecao == pytest.approx(a["projecao"])
        assert meta_turno == pytest.approx(a["meta_turno"])
        assert uph == pytest.approx(a["uph"])
        assert farol == a["farol"]
