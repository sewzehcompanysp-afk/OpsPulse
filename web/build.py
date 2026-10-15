"""Monta web/index.html a partir do template e da base de exemplo.

Uso: python web/build.py
Gera uma página única, sem dependências, pronta para o GitHub Pages.
"""
from pathlib import Path

AQUI = Path(__file__).parent
template = (AQUI / "index.template.html").read_text(encoding="utf-8")
amostra = (AQUI.parent / "data" / "exemplo_producao.csv").read_text(encoding="utf-8").strip()
corpo = template.replace("__AMOSTRA__", amostra)

corte = corpo.index('<div class="wrap">')
cabeca, resto = corpo[:corte], corpo[corte:]
html = (
    "<!doctype html>\n<html lang=\"pt-BR\">\n<head>\n<meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
    + cabeca
    + "</head>\n<body>\n"
    + resto
    + "\n</body>\n</html>\n"
)
(AQUI / "index.html").write_text(html, encoding="utf-8")
print(f"web/index.html gerado ({len(html) // 1024} KB)")
