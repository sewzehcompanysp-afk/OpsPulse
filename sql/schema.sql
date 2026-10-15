-- Tabela de entrada do OpsPulse: uma linha por área e por hora (data e hora do calendário).
DROP TABLE IF EXISTS producao;
CREATE TABLE producao (
  data      TEXT    NOT NULL,  -- AAAA-MM-DD
  hora      INTEGER NOT NULL,  -- 0 a 23
  area      TEXT    NOT NULL,
  volume    REAL    NOT NULL,
  meta      REAL    NOT NULL,
  headcount REAL               -- opcional
);
