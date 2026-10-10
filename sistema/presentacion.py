"""Formato de los resultados: texto plano para los reportes Markdown y paneles,
tablas y colores (rich) para la consola."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .busqueda import Resultado
from .consola import Group, Padding, Panel, RegexHighlighter, Table, Text, box, tabla_rich
from .red import RedTransporte

NOMBRES_ALGORITMO = {
    "a_estrella": "A* (A estrella)",
    "costo_uniforme": "Costo uniforme",
    "voraz": "Primero el mejor voraz",
    "amplitud": "Primero en amplitud",
}

# Un color por troncal para distinguirlas en la consola; una troncal nueva sale en negrita
COLOR_TRONCAL = {"A": "bright_blue", "B": "green", "D": "magenta", "E": "dark_orange", "F": "red",
                 "J": "yellow", "K": "cyan"}


def estilo_troncal(codigo: Optional[str]) -> str:
    return f"bold {COLOR_TRONCAL[codigo]}" if codigo in COLOR_TRONCAL else "bold"


def texto_troncales(codigos: Sequence[str]) -> Text:
    """Códigos de troncal separados por comas, cada uno con su color."""
    return Text(", ").join(Text(c, style=estilo_troncal(c)) for c in codigos)


def leyenda_troncales(red: RedTransporte) -> Text:
    """Código y nombre de cada troncal con su color, ej. A Caracas · B Autopista Norte."""
    return Text("  ·  ", style="nota").join(Text(f"{c} {n}", style=estilo_troncal(c))
                                            for c, n in sorted(red.troncales.items()))


def texto_recorrido(estaciones: Sequence[str]) -> Text:
    """Estaciones de un recorrido unidas por flechas."""
    return Text(" → ", style="nota").join(Text(e, style="estacion") for e in estaciones)


def instrucciones(red: RedTransporte, r: Resultado, detalle: bool = False) -> List[Tuple[str, int, Text]]:
    """Agrupa los pasos en tramos legibles: abordar -> viajar N paradas -> transbordo...
    Cada línea es (número del paso o "", sangría adicional, texto con colores): la
    consola la dibuja en columnas y el reporte usa su texto plano (texto_instrucciones)."""
    lineas: List[Tuple[str, int, Text]] = []
    n = 0
    tramo_estaciones: List[str] = []
    tramo_min = 0.0
    tramo_troncal = None

    def troncal(codigo):
        return red.nombre_troncal(codigo), estilo_troncal(codigo)

    def paso(*partes) -> None:
        nonlocal n
        n += 1
        lineas.append((f"{n}.", 0, Text.assemble(*partes)))

    def cerrar_tramo():
        nonlocal tramo_estaciones, tramo_min
        if len(tramo_estaciones) > 1:
            lineas.append(("", 0, Text.assemble(f"Viaje {len(tramo_estaciones) - 1} parada(s) hasta ",
                                                (tramo_estaciones[-1], "estacion"), f" (~{tramo_min:.1f} min).")))
            if detalle:
                lineas.append(("", 2, Text(" -> ".join(tramo_estaciones), style="nota")))
        tramo_estaciones, tramo_min = [], 0.0

    for p in r.pasos:
        if p.accion == "abordar":
            cerrar_tramo()
            espera = f" (espera ~{p.minutos:.0f} min)" if p.minutos else ""
            paso("Aborde la troncal ", troncal(p.troncal), " en ", (p.desde, "estacion"), f"{espera}.")
            tramo_troncal, tramo_estaciones = p.troncal, [p.desde]
        elif p.accion == "viajar":
            if not tramo_estaciones:
                tramo_estaciones = [p.desde]
            tramo_estaciones.append(p.hacia)
            tramo_min += p.minutos
        elif p.accion == "transbordo":
            cerrar_tramo()
            paso("Transbordo en ", (p.desde, "estacion"), ": de ", troncal(tramo_troncal), " a ",
                 troncal(p.troncal), f" (~{p.minutos:.0f} min).")
            tramo_troncal, tramo_estaciones = p.troncal, [p.desde]
        elif p.accion == "caminar":
            cerrar_tramo()
            paso("Camine de ", (p.desde, "estacion"), " a ", (p.hacia, "estacion"),
                 f" por la conexión peatonal (~{p.minutos:.0f} min).")
    cerrar_tramo()
    return lineas


def texto_instrucciones(red: RedTransporte, r: Resultado, detalle: bool = False) -> List[str]:
    """Las instrucciones en texto plano: " 1. Aborde ...", "    Viaje ..."."""
    return [f" {numero} {t.plain}" if numero else " " * (4 + sangria) + t.plain
            for numero, sangria, t in instrucciones(red, r, detalle)]


def formatear_ruta(red: RedTransporte, r: Resultado, detalle: bool = False) -> str:
    salida = [f"=== Ruta: {r.origen} -> {r.destino} ===",
              f"Algoritmo: {NOMBRES_ALGORITMO.get(r.algoritmo, r.algoritmo)} | Criterio: {r.criterio}"]
    if red.cerradas:
        salida.append(f"Estaciones cerradas: {', '.join(red.cerradas)}")
    salida.append("")
    if not r.encontrado:
        salida.append("No existe una ruta con las condiciones actuales de la red.")
    elif not r.pasos:
        salida.append("El origen y el destino son la misma estación.")
    else:
        salida.extend(texto_instrucciones(red, r, detalle))
        salida.append("")
        salida.append(f"Resumen: ~{r.minutos:.1f} min | {r.transbordos} transbordo(s) | "
                      f"{r.paradas} parada(s)")
    salida.append(f"Búsqueda: {r.nodos_expandidos} nodos expandidos, {r.nodos_generados} generados, "
                  f"frontera máx. {r.max_frontera}, {r.tiempo_ms:.2f} ms")
    return "\n".join(salida)


def panel_ruta(red: RedTransporte, r: Resultado, detalle: bool = False) -> Panel:
    """La ruta para la consola: pasos, resumen y métricas de la búsqueda en un panel."""
    lineas = [Text.assemble((NOMBRES_ALGORITMO.get(r.algoritmo, r.algoritmo), "dato"),
                            (f" · criterio: {r.criterio}", "nota"))]
    if red.cerradas:
        lineas.append(Text.assemble(("Estaciones cerradas: ", "nota"), (", ".join(red.cerradas), "error")))
    lineas.append(Text())
    if not r.encontrado:
        lineas.append(Text("No existe una ruta con las condiciones actuales de la red.", style="error"))
    elif not r.pasos:
        lineas.append(Text("El origen y el destino son la misma estación.", style="aviso"))
    else:
        # Número del paso en su propia columna: los textos largos se ajustan con sangría
        pasos = Table.grid(padding=(0, 1))
        pasos.add_column(justify="right", style="tecla")
        pasos.add_column()
        for numero, sangria, t in instrucciones(red, r, detalle):
            pasos.add_row(numero, Padding(t, (0, 0, 0, sangria)) if sangria else t)
        lineas += [pasos, Text(), Text(f"Resumen: ~{r.minutos:.1f} min · {r.transbordos} transbordo(s) · "
                                f"{r.paradas} parada(s)", style="resumen")]
    lineas.append(Text(f"Búsqueda: {r.nodos_expandidos} nodos expandidos, {r.nodos_generados} generados, "
                       f"frontera máx. {r.max_frontera}, {r.tiempo_ms:.2f} ms", style="nota"))
    return Panel(Group(*lineas), title=Text.assemble("Ruta: ", r.origen, " → ", r.destino, style="titulo"),
                 title_align="left", border_style="borde", box=box.ROUNDED, expand=False, padding=(0, 2))


def tabla(encabezados: Sequence[str], filas: Sequence[Sequence[object]]) -> str:
    textos = [[str(c) for c in f] for f in filas]
    anchos = [max(len(h), *(len(f[i]) for f in textos)) if textos else len(h)
              for i, h in enumerate(encabezados)]
    linea = lambda celdas: " | ".join(c.ljust(anchos[i]) for i, c in enumerate(celdas))
    return "\n".join([linea(encabezados), "-+-".join("-" * a for a in anchos), *(linea(f) for f in textos)])


def formatear_comparacion(resultados: Sequence[Resultado]) -> str:
    filas = []
    for r in resultados:
        if r.encontrado:
            filas.append([NOMBRES_ALGORITMO.get(r.algoritmo, r.algoritmo), f"{r.minutos:.1f}", r.transbordos,
                          r.paradas, r.nodos_expandidos, r.nodos_generados, f"{r.tiempo_ms:.2f}"])
        else:
            filas.append([NOMBRES_ALGORITMO.get(r.algoritmo, r.algoritmo), "sin ruta", "-", "-",
                          r.nodos_expandidos, r.nodos_generados, f"{r.tiempo_ms:.2f}"])
    return tabla(["Algoritmo", "Minutos", "Transb.", "Paradas", "Expandidos", "Generados", "ms"], filas)


def tabla_comparacion(resultados: Sequence[Resultado]) -> Table:
    """Las estrategias lado a lado para la consola: en verde el menor tiempo y la que
    expandió menos nodos; en amarillo, un tiempo peor que el óptimo."""
    encontrados = [r for r in resultados if r.encontrado]
    mejor = min((round(r.minutos, 1) for r in encontrados), default=None)
    menos_nodos = min((r.nodos_expandidos for r in encontrados), default=None)
    filas = []
    for r in resultados:
        nombre = Text(NOMBRES_ALGORITMO.get(r.algoritmo, r.algoritmo), style="dato")
        if r.encontrado:
            filas.append([nombre, Text(f"{r.minutos:.1f}", style="ok" if round(r.minutos, 1) == mejor else "aviso"),
                          r.transbordos, r.paradas,
                          Text(str(r.nodos_expandidos), style="ok" if r.nodos_expandidos == menos_nodos else ""),
                          r.nodos_generados, f"{r.tiempo_ms:.2f}"])
        else:
            filas.append([nombre, Text("sin ruta", style="error"), "-", "-", r.nodos_expandidos,
                          r.nodos_generados, f"{r.tiempo_ms:.2f}"])
    return tabla_rich(["Algoritmo", "Minutos", "Transb.", "Paradas", "Expandidos", "Generados", "ms"], filas)


class ResaltadorLogica(RegexHighlighter):
    """Colores para hechos, reglas y árboles de prueba de la base de conocimiento:
    variables en cian, constantes en verde, [regla Rn] en magenta y [hecho] en verde."""
    base_style = "logica."
    highlights = [
        r"(?P<conector>[├└│─]+)",
        r"\b(?P<variable>[A-Z_][A-Za-z0-9_]*)\b",
        r"(?P<cadena>\"[^\"]*\"|'[^']*')",
        r"(?P<operador>:-)",
        r"\b(?P<negacion>no)\b",
        r"(?m)^\s*(?P<regla>R\d+):",
        r"(?P<regla>\[regla R\d+\])",
        r"(?P<hecho>\[hecho\])",
        r"(?P<verificado>\[verificado\])",
        r"(?P<falso>NO se puede demostrar)",
        r"(?P<titulo>Reglas aplicadas:)",
    ]
