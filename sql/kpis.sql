-- OpsPulse em SQL (SQLite 3.25+; a lógica porta para PostgreSQL, SQL Server ou BigQuery
-- trocando as funções de data).
--
-- Mesmas regras das versões web e Python:
--   * T1 06h-14h, T2 14h-22h, T3 22h-06h. Horas de 00h a 05h vão para o T3 do dia anterior.
--   * Atingimento = realizado / meta acumulada.
--   * Meta do turno = meta acumulada + meta média por hora x horas que faltam.
--   * Projeção = realizado + média das 2 últimas horas x horas que faltam.
--   * Farol: verde >= 95%, amarelo >= 85%, vermelho abaixo.
--
-- Uso:
--   sqlite3 opspulse.db < sql/schema.sql
--   sqlite3 opspulse.db -cmd ".import --csv --skip 1 data/exemplo_producao.csv producao" < sql/kpis.sql

DROP VIEW IF EXISTS v_alertas;
DROP VIEW IF EXISTS v_total_turno;
DROP VIEW IF EXISTS v_area_turno;
DROP VIEW IF EXISTS v_hora_a_hora;
DROP VIEW IF EXISTS v_base;

-- 1. Cada linha ganha data operacional, turno e posição da hora dentro do turno (0 a 7)
CREATE VIEW v_base AS
WITH t AS (
  SELECT
    date(data) AS data_cal,
    CAST(hora AS INTEGER) AS hora,
    area,
    CAST(volume AS REAL) AS volume,
    CAST(meta AS REAL) AS meta,
    CAST(NULLIF(headcount, '') AS REAL) AS headcount,
    CASE
      WHEN CAST(hora AS INTEGER) BETWEEN 6 AND 13 THEN 'T1'
      WHEN CAST(hora AS INTEGER) BETWEEN 14 AND 21 THEN 'T2'
      ELSE 'T3'
    END AS turno
  FROM producao
)
SELECT
  CASE WHEN turno = 'T3' AND hora < 6 THEN date(data_cal, '-1 day') ELSE data_cal END AS data_op,
  turno,
  (hora - CASE turno WHEN 'T1' THEN 6 WHEN 'T2' THEN 14 ELSE 22 END + 24) % 24 AS pos,
  hora, area, volume, meta, headcount
FROM t;

-- 2. Hora a hora por área, com a ordem das horas mais recentes primeiro
CREATE VIEW v_hora_a_hora AS
SELECT
  data_op, turno, area, pos,
  SUM(volume) AS volume,
  SUM(meta) AS meta,
  SUM(headcount) AS headcount,
  ROW_NUMBER() OVER (PARTITION BY data_op, turno, area ORDER BY pos DESC) AS recencia
FROM v_base
GROUP BY data_op, turno, area, pos;

-- 3. Indicadores por área e turno
CREATE VIEW v_area_turno AS
WITH a AS (
  SELECT
    data_op, turno, area,
    COUNT(*) AS horas,
    SUM(volume) AS realizado,
    SUM(meta) AS meta_acum,
    SUM(headcount) AS headcount,
    AVG(CASE WHEN recencia <= 2 THEN volume END) AS ritmo
  FROM v_hora_a_hora
  GROUP BY data_op, turno, area
)
SELECT
  data_op, turno, area, horas, realizado, meta_acum,
  realizado / meta_acum AS atingimento,
  meta_acum + (meta_acum / horas) * (8 - horas) AS meta_turno,
  realizado + ritmo * (8 - horas) AS projecao,
  (realizado + ritmo * (8 - horas)) / (meta_acum + (meta_acum / horas) * (8 - horas)) AS proj_pct,
  realizado / NULLIF(headcount, 0) AS uph,
  CASE
    WHEN realizado / meta_acum >= 0.95 THEN 'verde'
    WHEN realizado / meta_acum >= 0.85 THEN 'amarelo'
    ELSE 'vermelho'
  END AS farol
FROM a;

-- 4. Total do turno
CREATE VIEW v_total_turno AS
SELECT
  data_op, turno,
  MAX(horas) AS horas_com_dado,
  SUM(realizado) AS realizado,
  SUM(meta_acum) AS meta_acum,
  SUM(realizado) / SUM(meta_acum) AS atingimento,
  SUM(meta_turno) AS meta_turno,
  SUM(projecao) AS projecao,
  SUM(projecao) / SUM(meta_turno) AS proj_pct,
  SUM(realizado) / SUM(realizado / uph) AS uph,
  CASE
    WHEN SUM(realizado) / SUM(meta_acum) >= 0.95 THEN 'verde'
    WHEN SUM(realizado) / SUM(meta_acum) >= 0.85 THEN 'amarelo'
    ELSE 'vermelho'
  END AS farol
FROM v_area_turno
GROUP BY data_op, turno;

-- 5. Alertas de farol e de projeção
CREATE VIEW v_alertas AS
SELECT data_op, turno, area,
       CASE farol WHEN 'vermelho' THEN 'critico' ELSE 'atencao' END AS severidade,
       area || ' está em ' || printf('%.1f%%', atingimento * 100) || ' da meta acumulada.' AS texto
FROM v_area_turno
WHERE farol <> 'verde'
UNION ALL
SELECT data_op, turno, area,
       CASE WHEN proj_pct < 0.85 THEN 'critico' ELSE 'atencao' END,
       area || ' deve fechar o turno com ' || printf('%.1f%%', proj_pct * 100) || ' da meta.'
FROM v_area_turno
WHERE horas < 8 AND proj_pct < 0.95;

-- Consulta de exemplo: o turno mais recente da base
.mode box
SELECT area, farol, CAST(realizado AS INT) AS realizado, CAST(meta_acum AS INT) AS meta_acum,
       printf('%.1f%%', atingimento * 100) AS atingimento, CAST(ROUND(projecao) AS INT) AS projecao,
       printf('%.1f', uph) AS uph
FROM v_area_turno
WHERE (data_op, turno) = (SELECT data_op, turno FROM v_base ORDER BY data_op DESC, turno DESC LIMIT 1);

SELECT severidade, texto FROM v_alertas
WHERE (data_op, turno) = (SELECT data_op, turno FROM v_base ORDER BY data_op DESC, turno DESC LIMIT 1)
ORDER BY severidade DESC, area;
