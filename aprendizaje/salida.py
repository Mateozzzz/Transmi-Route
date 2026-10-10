"""Utilidades de salida compartidas por las actividades (consola y Markdown)."""
from __future__ import annotations

import os
import sys
from typing import Sequence


def utf8_en_consola() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")  # Windows (cmd/PowerShell)
        except (AttributeError, ValueError):
            pass


def tabla_md(encabezados: Sequence[str], filas: Sequence[Sequence[object]]) -> str:
    lineas = ["| " + " | ".join(encabezados) + " |",
              "|" + "|".join("---" for _ in encabezados) + "|"]
    lineas += ["| " + " | ".join(str(c) for c in f) + " |" for f in filas]
    return "\n".join(lineas)


def pct(v: float, decimales: int = 1) -> str:
    return f"{v * 100:.{decimales}f} %"


def escribir(ruta: str, texto: str) -> str:
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return ruta


def ruta_relativa(ruta: str, base: str) -> str:
    return os.path.relpath(ruta, base).replace(os.sep, "/")
