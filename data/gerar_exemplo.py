"""Gera a base fictícia data/exemplo_producao.csv usada pelas três versões do OpsPulse.

Nenhum dado aqui vem de empresa real: volumes, metas e headcount são sintéticos.
Turnos: T1 06h-14h, T2 14h-22h, T3 22h-06h (vira a meia-noite).
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

AREAS = {  # meta por hora, UPH alvo (unidades por pessoa-hora)
    "Recebimento": (1200, 80),
    "Armazenagem": (900, 60),
    "Picking": (1800, 110),
    "Packing": (1600, 95),
    "Expedição": (1500, 100),
}
TURNOS = {"T1": range(6, 14), "T2": range(14, 22), "T3": [22, 23, 0, 1, 2, 3, 4, 5]}
INICIO = date(2026, 10, 8)
DIAS = 8  # o último dia fica incompleto: T1 fechado e T2 até 17h59

# Roteiro do último turno para o painel abrir com algo para analisar
ROTEIRO_ULTIMO = {
    "Picking": [1.00, 0.95, 0.88, 0.74],     # ritmo caindo
    "Expedição": [0.80, 0.78, 0.81, 0.76],   # abaixo da meta o turno todo
}

linhas = []
for d in range(DIAS):
    dia_op = INICIO + timedelta(days=d)
    ultimo = d == DIAS - 1
    for turno, horas in TURNOS.items():
        if ultimo and turno == "T3":
            continue
        for i, h in enumerate(horas):
            if ultimo and turno == "T2" and h >= 18:
                continue
            data_cal = dia_op + timedelta(days=1) if (turno == "T3" and h < 6) else dia_op
            for area, (meta, uph) in AREAS.items():
                if ultimo and turno == "T2" and area in ROTEIRO_ULTIMO:
                    fator = ROTEIRO_ULTIMO[area][i]
                else:
                    fator = random.gauss(1.0, 0.05)
                    if i == 0:
                        fator *= 0.9          # aquecimento do turno
                    if i == 4:
                        fator *= 0.93          # pausa de refeição
                    if turno == "T3":
                        fator *= 0.97
                volume = max(0, round(meta * fator))
                hc = max(1, round(meta / uph) + random.choice([-1, 0, 0, 1]))
                linhas.append([data_cal.isoformat(), h, area, volume, meta, hc])

saida = Path(__file__).with_name("exemplo_producao.csv")
with saida.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["data", "hora", "area", "volume", "meta", "headcount"])
    w.writerows(linhas)
print(f"{len(linhas)} linhas em {saida}")
