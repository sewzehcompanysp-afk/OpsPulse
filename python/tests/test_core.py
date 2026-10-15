from pathlib import Path

import pytest

import opspulse_core as core

AMOSTRA = Path(__file__).resolve().parents[2] / "data" / "exemplo_producao.csv"


@pytest.fixture(scope="module")
def base():
    return core.ler_csv(str(AMOSTRA))


def test_le_amostra_inteira(base):
    assert len(base) == 900
    assert base.attrs["ignoradas"] == 0


def test_t3_vira_a_meia_noite(base):
    # 02h do dia 15 pertence ao T3 da data operacional 14
    madrugada = base[(base["turno"] == "T3") & (base["hora"] == 2)]
    assert "2026-10-14" in set(madrugada["data_op"])
    assert core.turno_da_hora(23) == ("T3", 1)
    assert core.turno_da_hora(5) == ("T3", 7)
    assert core.turno_da_hora(6) == ("T1", 0)


def test_turno_em_andamento(base):
    res = core.resumir(base, "2026-10-15", "T2")
    assert res.horas_com_dado == 4
    assert res.em_andamento
    assert res.ultima_hora == 17
    exp = res.areas.set_index("area").loc["Expedição"]
    assert exp["farol"] == "vermelho"
    assert exp["meta_turno"] == 12000
    # projeção = realizado + média das 2 últimas horas x 4 horas restantes
    assert exp["projecao"] == pytest.approx(exp["realizado"] + exp["ritmo"] * 4)


def test_turno_fechado_projecao_igual_realizado(base):
    res = core.resumir(base, "2026-10-14", "T3")
    assert not res.em_andamento
    assert res.total["projecao"] == pytest.approx(res.total["realizado"])


def test_alertas_ordenados_e_queda_de_ritmo(base):
    res = core.resumir(base, "2026-10-15", "T2")
    lista = core.alertas(res)
    assert lista[0]["sev"] == "critico"
    assert any("Picking caiu" in a["texto"] for a in lista)


def test_csv_brasileiro_com_ponto_e_virgula():
    texto = "Data;Hora;Setor;Realizado;Meta;HC\n15/10/2026;14:00;Picking;1.234,0;1500;10\n16/10/2026;02:00;Picking;900;1500;9\n"
    df = core.ler_csv(texto)
    assert list(df["volume"]) == [1234.0, 900.0]
    assert list(df["data_op"]) == ["2026-10-15", "2026-10-15"]
    assert list(df["turno"]) == ["T2", "T3"]


def test_coluna_faltando():
    with pytest.raises(core.ErroDeArquivo, match="Faltam as colunas"):
        core.ler_csv("a,b\n1,2\n")


def test_limites_do_farol():
    assert core.farol(0.95) == "verde"
    assert core.farol(0.9) == "amarelo"
    assert core.farol(0.8) == "vermelho"
    assert core.farol(0.9, {"verde": 0.9, "amarelo": 0.8}) == "verde"
