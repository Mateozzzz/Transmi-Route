"""Consola con colores (librería rich) compartida por las tres actividades.

Es el único módulo que importa rich: los demás toman de aquí la consola, el tema,
las utilidades y las clases de rich que usan. Así, si falta la librería, el
programa lo explica en lugar de terminar con una traza de error.

Los textos que vienen de los datos (estaciones, consultas, reglas, mensajes de
error) se imprimen siempre como Text: rich tomaría los corchetes de "[hecho]" o
"[soporte 83, ...]" como etiquetas de estilo si se pasaran como cadenas.
"""
from __future__ import annotations

import re
import sys
from typing import Iterable, Optional, Sequence, Tuple

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group, RenderableType
    from rich.highlighter import RegexHighlighter
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
except ImportError:  # pragma: no cover - depende de lo instalado
    try:
        sys.stderr.reconfigure(encoding="utf-8")  # el mensaje sale antes de que main() configure la consola
    except (AttributeError, ValueError):
        pass
    sys.exit("Falta la librería rich. Instálela con:  pip install -r requirements.txt")

__all__ = ["Align", "Group", "Padding", "Panel", "RegexHighlighter", "Rule", "Table", "Text", "box",
           "TEMA", "consola", "consola_error", "encabezado", "subtitulo", "celda", "tabla_rich", "pares",
           "exito", "aviso", "error"]

TEMA = Theme({
    # menús
    "marca": "bold white on red",
    "titulo": "bold red",
    "seccion": "bold yellow",
    "tecla": "bold cyan",
    "opcion": "bold",
    "descripcion": "grey62",
    "etiqueta": "magenta",
    "pregunta": "bold",
    # mensajes
    "nota": "grey50",
    "ok": "green",
    "aviso": "yellow",
    "error": "bold red",
    "comando": "green",
    "resumen": "bold green",
    # datos
    "encabezado": "bold",
    "dato": "bold",
    "estacion": "bold",
    "borde": "grey50",
    "chispa": "cyan",
    # nivel de demanda previsto (Actividad 3)
    "nivel.bajo": "bold green",
    "nivel.medio": "bold yellow",
    "nivel.alto": "bold red",
    # reglas SI ... ENTONCES y árbol en texto (Actividad 3)
    "arbol.clave": "bold",
    "arbol.conector": "grey50",
    "arbol.bajo": "green",
    "arbol.medio": "yellow",
    "arbol.alto": "red",
    # hechos, reglas y árboles de prueba de la base de conocimiento (Actividad 2)
    "logica.conector": "grey50",
    "logica.variable": "cyan",
    "logica.cadena": "green",
    "logica.operador": "grey50",
    "logica.negacion": "red",
    "logica.regla": "magenta",
    "logica.hecho": "green",
    "logica.verificado": "grey50",
    "logica.falso": "bold red",
    "logica.titulo": "bold default",
})

# Sin file= fijo: rich escribe en el sys.stdout / sys.stderr de cada momento, así que
# la salida se puede redirigir (pruebas, archivos). Si el programa arranca sin
# terminal (python main.py ... > salida.txt), el texto sale sin códigos de color.
consola = Console(theme=TEMA, highlight=False, emoji=False)
consola_error = Console(theme=TEMA, highlight=False, emoji=False, stderr=True)

_NUMERO = re.compile(r"[~<>≤≥+-]?\s?\d[\d.,]*\s?%?")


def celda(valor: object) -> RenderableType:
    """Lo que rich sabe dibujar (Text, tablas, paneles) se deja igual; lo demás se
    convierte en Text, sin interpretar marcado."""
    return valor if hasattr(valor, "__rich_console__") or hasattr(valor, "__rich__") else Text(str(valor))


def encabezado(titulo: str, nota: Optional[str] = None) -> None:
    """Abre un bloque de la salida: una línea con el título y, debajo, una nota en gris."""
    consola.print(Rule(Text(titulo, style="encabezado"), align="left", style="red"))
    if nota:
        consola.print(Text(nota, style="nota"))


def subtitulo(texto: str) -> None:
    """Título de una tabla o de una parte de un bloque."""
    consola.print()
    consola.print(Text(texto, style="encabezado"))


def tabla_rich(encabezados: Sequence[str], filas: Iterable[Sequence[object]],
               estilos_fila: Optional[Sequence[Optional[str]]] = None, compacta: bool = False) -> Table:
    """Tabla con bordes redondeados y encabezado en negrita; las columnas numéricas
    se alinean a la derecha. compacta=True quita los bordes verticales para las tablas anchas.

    Si la terminal es angosta, rich ajusta primero las columnas de texto: las que no
    tienen espacios (números, mini gráficos) no se parten mientras la tabla quepa con
    las de texto en unos 10 caracteres; si ni así cabe, rich reparte el ancho entre todas."""
    celdas = [[celda(c) for c in f] for f in filas]
    t = Table(box=box.SIMPLE_HEAD if compacta else box.ROUNDED, border_style="borde", header_style="encabezado",
              show_edge=not compacta, pad_edge=not compacta, collapse_padding=compacta)
    columnas = []
    for i, h in enumerate(encabezados):
        textos = [getattr(f[i], "plain", " ") for f in celdas if i < len(f)]
        valores = [v for v in textos if v not in ("", "-")]
        numerica = bool(valores) and all(_NUMERO.fullmatch(v) for v in valores)
        ancho = max([len(str(h))] + [len(v) for v in textos])
        columnas.append((h, numerica, any(" " in v for v in textos), ancho))
    separadores = 2 * (len(columnas) - 1) if compacta else 3 * len(columnas) + 1
    minimo = sum(min(10, ancho) if partible else ancho for _, _, partible, ancho in columnas) + separadores
    for h, numerica, partible, _ in columnas:
        t.add_column(celda(h), justify="right" if numerica else "left",
                     no_wrap=not partible and minimo <= consola.width)
    for i, f in enumerate(celdas):
        t.add_row(*f, style=estilos_fila[i] if estilos_fila else None)
    return t


def pares(datos: Iterable[Tuple[str, object]]) -> Table:
    """Resumen en dos columnas: etiqueta en gris y valor (texto, número o una tabla pequeña)."""
    t = Table.grid(padding=(0, 2))
    t.add_column(style="nota", no_wrap=True)
    t.add_column()
    for etiqueta, valor in datos:
        t.add_row(celda(etiqueta), celda(valor))
    return t


def _mensaje(icono: str, estilo: str, texto: object, destino: Console = consola) -> None:
    # El estilo es la base de toda la línea: las partes con estilo propio lo conservan
    destino.print(Text.assemble("  ", f"{icono} ", celda(texto), style=estilo))


def exito(texto: object) -> None:
    _mensaje("✔", "ok", texto)


def aviso(texto: object) -> None:
    _mensaje("⚠", "aviso", texto)


def error(texto: object, stderr: bool = False) -> None:
    _mensaje("✘ Error:", "error", texto, consola_error if stderr else consola)
