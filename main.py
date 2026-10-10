#!/usr/bin/env python3
"""
Sistema inteligente de rutas en TransMilenio: punto de entrada único de las
Actividades 2, 3 y 4.

    python main.py                  menú interactivo con las tres actividades
    python main.py -h               comandos organizados por actividad

Actividad 2 - base de conocimiento, motor de inferencia y búsqueda A*:
    python main.py ruta "Portal Norte" "Portal Américas"
    python main.py comparar "Portal 80" "Universidades"
    python main.py consultar "transbordo(E, T1, T2)"
    python main.py explicar transbordo Ricaurte E F
    python main.py estaciones --troncal K
    python main.py reglas
    python main.py escenarios --salida resultados_pruebas.md

Actividades 3 y 4 - se reenvían a sus módulos (igual que python -m actividadN):
    python main.py actividad3 predecir --estacion "Portal Norte" --hora 6
    python main.py actividad4 agrupar -k 5
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from sistema.busqueda import ALGORITMOS, ProblemaRuta, Resultado, buscar_ruta
from sistema.consola import (Align, Group, Padding, Panel, Rule, Table, Text, aviso, box, consola, encabezado,
                             error, exito, pares, subtitulo, tabla_rich)
from sistema.logica import ErrorLogico
from sistema.presentacion import (ResaltadorLogica, formatear_comparacion, formatear_ruta, leyenda_troncales,
                                  panel_ruta, tabla_comparacion, texto_recorrido, texto_troncales)
from sistema.red import RedTransporte

DIR_RAIZ = os.path.dirname(os.path.abspath(__file__))


def _utf8_en_consola() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")  # Windows (cmd/PowerShell)
        except (AttributeError, ValueError):
            pass


def _convertir(valor: str):
    try:
        return int(valor)
    except ValueError:
        try:
            return float(valor)
        except ValueError:
            return valor


# ---------------------------------------------------------------------------
# Actividad 2: comandos sobre la base de conocimiento y la búsqueda
# ---------------------------------------------------------------------------

def cmd_ruta(args) -> None:
    red = RedTransporte(cerradas=args.cerrar or [])
    r = buscar_ruta(red, args.origen, args.destino, args.algoritmo, args.criterio)
    consola.print(panel_ruta(red, r, detalle=args.detalle))


def cmd_comparar(args) -> None:
    red = RedTransporte(cerradas=args.cerrar or [])
    resultados = [buscar_ruta(red, args.origen, args.destino, a, args.criterio) for a in ALGORITMOS]
    encabezado(f"Comparación de estrategias: {resultados[0].origen} → {resultados[0].destino}",
               f"Criterio: {args.criterio} · en verde, el mejor tiempo y la que expandió menos nodos")
    consola.print(tabla_comparacion(resultados))
    ruta = resultados[0].estaciones_ruta
    consola.print(Text.assemble(("Ruta encontrada por A*: ", "nota"),
                                texto_recorrido(ruta) if ruta else Text("sin ruta", style="error")))


def cmd_consultar(args) -> None:
    red = RedTransporte(cerradas=args.cerrar or [])
    for ruta in getattr(args, "con", None) or []:
        # Las rutas relativas también se buscan desde la raíz del proyecto
        if not os.path.exists(ruta) and os.path.exists(os.path.join(DIR_RAIZ, ruta)):
            ruta = os.path.join(DIR_RAIZ, ruta)
        if not os.path.exists(ruta):
            raise ValueError(f"No existe el archivo {ruta}")
        red.kb.cargar_archivo(ruta)
    filas = red.kb.consultar(args.consulta)
    if not filas:
        aviso("No hay resultados (la consulta es falsa en la base de conocimiento).")
        return
    if not filas[0]:
        exito("Verdadero.")
        return
    columnas = list(filas[0])
    consola.print(tabla_rich(columnas, [[f.get(c, "") for c in columnas] for f in filas[: args.limite]]))
    if len(filas) > args.limite:
        consola.print(Text(f"... ({len(filas) - args.limite} resultados más; use --limite)", style="nota"))
    consola.print(Text(f"{len(filas)} resultado(s).", style="nota"))


def cmd_explicar(args) -> None:
    red = RedTransporte(cerradas=args.cerrar or [])
    valores = []
    for v in args.argumentos:
        c = _convertir(v)
        # Permite escribir nombres sin tildes: se corrige si es una estación
        if isinstance(c, str):
            try:
                c = red.resolver_nombre(c) if len(c) > 1 else c
            except ValueError:
                pass
        valores.append(c)
    consola.print(ResaltadorLogica()(red.kb.explicar((args.predicado, tuple(valores)))))


def cmd_estaciones(args) -> None:
    red = RedTransporte()
    if args.troncal:
        codigo = args.troncal.upper()
        if codigo not in red.troncales:
            raise ValueError(f"Troncal desconocida: {codigo}. Opciones: {', '.join(sorted(red.troncales))}")
        # Recorre la troncal desde su cabecera usando los hechos siguiente/3
        cabeceras = [e for e, _ in red.kb.buscar("cabecera", None, codigo)]
        orden, actual = [], (cabeceras[0] if cabeceras else None)
        while actual is not None:
            orden.append(actual)
            sig = [b for _, b, _ in red.kb.buscar("siguiente", actual, None, codigo)]
            actual = sig[0] if sig else None
        consecutivos = set(zip(orden, orden[1:]))
        ramales = [(a, b) for a, b, _ in red.kb.buscar("siguiente", None, None, codigo)
                   if (a, b) not in consecutivos]
        encabezado(f"Troncal {red.nombre_troncal(codigo)}: {len(orden) + len(ramales)} estaciones",
                   "En orden desde la cabecera; la última columna indica dónde hay transbordo.")
        consola.print(tabla_rich(["#", "Estación", "Transbordo a"],
                                 [[i, Text(e, style="estacion"),
                                   texto_troncales([t for t in red.troncales_de(e) if t != codigo])]
                                  for i, e in enumerate(orden, 1)]))
        for a, b in ramales:
            consola.print(Text.assemble(("Ramal/interconector: ", "nota"), texto_recorrido([a, b])))
        return
    consola.print(Text.assemble(("Troncales: ", "nota"), leyenda_troncales(red)))
    consola.print(tabla_rich(["Estación", "Troncales"],
                             [[Text(e, style="estacion"), texto_troncales(red.troncales_de(e))]
                              for e in red.estaciones]))
    consola.print(Text(f"{len(red.estaciones)} estaciones en {len(red.troncales)} troncales.", style="nota"))


def cmd_reglas(args) -> None:
    red = RedTransporte()
    resaltar = ResaltadorLogica()
    encabezado("Reglas de la base de conocimiento", "conocimiento/reglas.kb")
    consola.print(tabla_rich(["Regla", "Definición"],
                             [[Text(r.etiqueta, style="logica.regla"), resaltar(str(r))] for r in red.kb.reglas]))
    e = red.estadisticas
    subtitulo("Encadenamiento hacia adelante")
    consola.print(pares([("Hechos base", e.hechos_base), ("Hechos derivados", e.hechos_derivados),
                         ("Reglas", e.reglas), ("Estratos", e.estratos), ("Iteraciones", e.iteraciones)]))


# ---------------------------------------------------------------------------
# Escenarios de prueba (evidencia para el documento de pruebas)
# ---------------------------------------------------------------------------

class Escenario:
    def __init__(self, nombre: str, origen: str, destino: str, esperado: str,
                 verificar: Callable[[Resultado], bool], cerradas: Sequence[str] = (),
                 criterio: str = "tiempo", comparar: bool = False):
        self.nombre, self.origen, self.destino = nombre, origen, destino
        self.esperado, self.verificar = esperado, verificar
        self.cerradas, self.criterio, self.comparar = list(cerradas), criterio, comparar

    def comando(self) -> str:
        base = "comparar" if self.comparar else "ruta"
        partes = [f'python main.py {base} "{self.origen}" "{self.destino}"']
        if self.criterio != "tiempo":
            partes.append(f"--criterio {self.criterio}")
        if self.cerradas:
            partes.append("--cerrar " + " ".join(f'"{c}"' for c in self.cerradas))
        return " ".join(partes)


ESCENARIOS = [
    Escenario("Viaje sobre una sola troncal", "Portal Norte", "Calle 100",
              "Ruta directa por la troncal B, sin transbordos.",
              lambda r: r.encontrado and r.transbordos == 0),
    Escenario("Un transbordo (norte -> centro)", "Portal Norte", "Av. Jiménez",
              "Troncal B hasta Héroes y transbordo a la troncal A (Caracas).",
              lambda r: r.encontrado and r.transbordos == 1 and "Héroes" in r.estaciones_ruta),
    Escenario("Elección entre corredores alternativos", "Portal Norte", "Ricaurte",
              "Existen dos caminos (NQS o Caracas + Américas); se elige el de menor tiempo.",
              lambda r: r.encontrado and "Paloquemao" in r.estaciones_ruta, comparar=True),
    Escenario("Viaje largo occidente-occidente", "Portal 80", "Portal Américas",
              "A* encuentra el mismo costo que costo uniforme expandiendo menos nodos.",
              lambda r: r.encontrado, comparar=True),
    Escenario("Uso de conexión peatonal", "Portal El Dorado", "Museo del Oro",
              "Troncal K hasta Universidades, túnel peatonal a Las Aguas y troncal J.",
              lambda r: r.encontrado and any(p.accion == "caminar" for p in r.pasos)),
    Escenario("Estación cerrada (replanificación)", "Portal Norte", "Ricaurte",
              "Con Paloquemao cerrada, la ruta evita esa estación y usa otro corredor.",
              lambda r: r.encontrado and "Paloquemao" not in r.estaciones_ruta, cerradas=["Paloquemao"]),
    Escenario("La búsqueda voraz no garantiza la mejor ruta", "Escuela Militar", "U. Nacional",
              "Voraz se deja guiar solo por la cercanía al destino y produce una ruta más lenta; A* es óptimo.",
              lambda r: r.encontrado and r.minutos < buscar_ruta(RedTransporte(), r.origen, r.destino, "voraz").minutos,
              comparar=True),
    Escenario("Sin ruta posible", "Portal Norte", "Calle 100",
              "Con Toberín cerrada, Portal Norte queda aislado: el sistema informa que no hay ruta.",
              lambda r: not r.encontrado, cerradas=["Toberín"]),
    Escenario("Nombres sin tildes ni mayúsculas", "heroes", "americas av boyaca",
              "El sistema reconoce 'Héroes' y 'Américas - Av. Boyacá'.",
              lambda r: r.encontrado and r.origen == "Héroes"),
    Escenario("Origen igual al destino", "Calle 45", "Calle 45",
              "Ruta vacía, costo 0.",
              lambda r: r.encontrado and not r.pasos),
]


def cmd_escenarios(args) -> None:
    md: List[str] = [
        "# Resultados de pruebas - Ruta óptima en TransMilenio",
        "",
        f"Generado automáticamente el {datetime.now():%Y-%m-%d %H:%M} con `python main.py escenarios`.",
        "",
    ]
    aprobados = 0
    filas = []
    for i, esc in enumerate(ESCENARIOS, 1):
        red = RedTransporte(cerradas=esc.cerradas)
        r = buscar_ruta(red, esc.origen, esc.destino, "a_estrella", esc.criterio)
        ok = esc.verificar(r)
        aprobados += ok
        md += [f"## Prueba {i}. {esc.nombre}", "",
               f"- **Comando:** `{esc.comando()}`",
               f"- **Resultado esperado:** {esc.esperado}",
               f"- **Veredicto:** {'APROBADA' if ok else 'FALLIDA'}", "",
               "```text", formatear_ruta(red, r), "```", ""]
        if esc.comparar:
            res = [buscar_ruta(red, esc.origen, esc.destino, a, esc.criterio) for a in ALGORITMOS]
            md += ["Comparación de estrategias de búsqueda:", "", "```text", formatear_comparacion(res), "```", ""]
        filas.append([i, esc.nombre, Text("✔ aprobada", style="ok") if ok else Text("✘ fallida", style="error")])
    md += [f"**Total: {aprobados}/{len(ESCENARIOS)} pruebas aprobadas.**", ""]
    with open(args.salida, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    encabezado("Escenarios de prueba", "Cada uno se resuelve con A* y se compara con su resultado esperado.")
    consola.print(tabla_rich(["#", "Escenario", "Resultado"], filas))
    consola.print(Text.assemble(
        (f"{aprobados}/{len(ESCENARIOS)} aprobadas.", "resumen" if aprobados == len(ESCENARIOS) else "error"),
        (f" Reporte guardado en {args.salida}", "nota")), soft_wrap=True)


# ---------------------------------------------------------------------------
# Actividades 3 y 4: se reenvían a sus módulos
# ---------------------------------------------------------------------------

MODULOS_ACTIVIDAD = {"actividad3": "actividad3.supervisado", "actividad4": "actividad4.no_supervisado"}


def ejecutar_actividad(actividad: str, argumentos: Sequence[str]) -> int:
    """Ejecuta un comando de la Actividad 3 o 4 con su propio analizador de argumentos,
    igual que python -m actividadN. El módulo se importa solo cuando se usa: así la
    Actividad 2 no depende de la carpeta aprendizaje/."""
    return importlib.import_module(MODULOS_ACTIVIDAD[actividad]).main(list(argumentos))


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------

AYUDA_GENERAL = """\
Sistema inteligente de rutas en TransMilenio: une las Actividades 2, 3 y 4.
Sin argumentos abre el menú interactivo.

Actividad 2 · Rutas óptimas (base de conocimiento + búsqueda A*)
  ruta ORIGEN DESTINO          mejor ruta: pasos, tiempo, transbordos y caminatas
  comparar ORIGEN DESTINO      amplitud, costo uniforme, voraz y A* en el mismo viaje
  consultar "CONSULTA"         consulta lógica, ej. "transbordo(E, T1, T2)"
  explicar PREDICADO ARG...    qué reglas y hechos demuestran un hecho
  estaciones [--troncal K]     estaciones con sus troncales, o una troncal en orden
  reglas                       las 15 reglas y las estadísticas de la inferencia
  escenarios                   10 escenarios de prueba -> resultados_pruebas.md

Actividad 3 · Demanda en las estaciones (árbol de decisión, datos reales)
  actividad3 COMANDO ...       importar, generar, explorar, entrenar, reglas,
                               predecir, ruta   (ayuda: python main.py actividad3 -h)

Actividad 4 · Tipos de estación (k-medias y agrupamiento jerárquico)
  actividad4 COMANDO ...       importar, generar, explorar, codo, agrupar
                               (ayuda: python main.py actividad4 -h)
"""

EJEMPLOS = """\
ejemplos:
  python main.py ruta "Portal El Dorado" "Museo del Oro"
  python main.py consultar "perfil_estacion(E, P)" --con actividad4/resultados/perfiles.kb
  python main.py actividad3 predecir --estacion "Portal Norte" --hora 6
  python main.py actividad4 agrupar -k 5

Ayuda de un comando: python main.py COMANDO -h
"""


class _Formato(argparse.RawDescriptionHelpFormatter):
    """Respeta los saltos de línea de las descripciones y escribe 'uso:' en español."""

    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "uso: " if prefix is None else prefix)


def _en_espanol(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser._positionals.title = "argumentos"
    parser._optionals.title = "opciones"
    parser.add_argument("-h", "--help", action="help", help="muestra esta ayuda y termina")
    return parser


def construir_parser() -> argparse.ArgumentParser:
    p = _en_espanol(argparse.ArgumentParser(
        prog="python main.py", usage="%(prog)s [COMANDO] [opciones]", description=AYUDA_GENERAL,
        epilog=EJEMPLOS, formatter_class=_Formato, add_help=False))
    # Los comandos ya se describen agrupados en AYUDA_GENERAL: no se repiten en la lista automática
    sub = p.add_subparsers(dest="comando", metavar="COMANDO", help=argparse.SUPPRESS)

    def comando(nombre: str, descripcion: str) -> argparse.ArgumentParser:
        return _en_espanol(sub.add_parser(nombre, description=descripcion, formatter_class=_Formato,
                                          add_help=False))

    def opcion_cerrar(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--cerrar", nargs="+", metavar="ESTACION",
                        help="estaciones fuera de servicio: se agregan como hechos cerrada/1 "
                             "y la red se vuelve a inferir")

    def origen_destino(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("origen", help="estación de origen (acepta nombres sin tildes, ej. heroes)")
        sp.add_argument("destino", help="estación de destino")

    criterios = {"choices": list(ProblemaRuta.CRITERIOS), "default": "tiempo",
                 "help": "tiempo (por defecto) minimiza los minutos; transbordos minimiza los "
                         "cambios de troncal"}

    sp = comando("ruta", "Calcula la mejor ruta entre dos estaciones con la búsqueda A* sobre la red\n"
                         "que infiere la base de conocimiento. Muestra cada paso (abordar, viajar,\n"
                         "transbordar, caminar), el tiempo estimado y cuántos nodos exploró.\n\n"
                         'Ejemplo: python main.py ruta "Portal El Dorado" "Museo del Oro"')
    origen_destino(sp)
    sp.add_argument("-a", "--algoritmo", choices=list(ALGORITMOS), default="a_estrella",
                    help="estrategia de búsqueda: a_estrella (por defecto; óptima e informada), "
                         "costo_uniforme (óptima, no informada), voraz (no garantiza la mejor ruta) "
                         "o amplitud (la de menos pasos)")
    sp.add_argument("-c", "--criterio", **criterios)
    sp.add_argument("-d", "--detalle", action="store_true", help="lista todas las estaciones intermedias")
    opcion_cerrar(sp)
    sp.set_defaults(func=cmd_ruta)

    sp = comando("comparar", "Ejecuta las cuatro estrategias sobre el mismo viaje: dos no informadas\n"
                             "(amplitud y costo uniforme) y dos informadas (voraz y A*), y compara\n"
                             "minutos, transbordos, paradas y nodos expandidos y generados.\n\n"
                             'Ejemplo: python main.py comparar "Escuela Militar" "U. Nacional"')
    origen_destino(sp)
    sp.add_argument("-c", "--criterio", **criterios)
    opcion_cerrar(sp)
    sp.set_defaults(func=cmd_comparar)

    sp = comando("consultar", "Responde una consulta lógica sobre los hechos de la base y lo que se\n"
                              "infiere de ellos. Las variables van en mayúscula; las constantes, entre\n"
                              "comillas simples.\n\n"
                              "Ejemplos:\n"
                              '  python main.py consultar "transbordo(E, T1, T2)"\n'
                              "  python main.py consultar \"puede_abordar('Ricaurte', T)\"\n"
                              '  python main.py consultar "perfil_estacion(E, P), estacion_de_integracion(E)"'
                              " --con actividad4/resultados/perfiles.kb")
    sp.add_argument("consulta", help='la consulta, ej. "transbordo(E, T1, T2)"')
    sp.add_argument("--limite", type=int, default=50, help="máximo de filas a mostrar (por defecto 50)")
    sp.add_argument("--con", nargs="+", metavar="ARCHIVO.kb",
                    help="hechos adicionales que se cargan antes de consultar, ej. los perfiles de "
                         "estación de la Actividad 4 (actividad4/resultados/perfiles.kb)")
    opcion_cerrar(sp)
    sp.set_defaults(func=cmd_consultar)

    sp = comando("explicar", "Muestra el árbol de prueba de un hecho: la regla que lo derivó y las\n"
                             "premisas que usó, hasta llegar a los hechos de la base.\n\n"
                             "Ejemplo: python main.py explicar transbordo Ricaurte E F")
    sp.add_argument("predicado", help="predicado del hecho, ej. transbordo, movimiento o cabecera")
    sp.add_argument("argumentos", nargs="*", help="argumentos del hecho, ej. Ricaurte E F")
    opcion_cerrar(sp)
    sp.set_defaults(func=cmd_explicar)

    sp = comando("estaciones", "Lista las estaciones con sus troncales o, con --troncal, una troncal en\n"
                               "orden desde su cabecera, indicando dónde hay transbordo.")
    sp.add_argument("--troncal", metavar="CODIGO", help="código de la troncal: A, B, D, E, F, J o K")
    sp.set_defaults(func=cmd_estaciones)

    sp = comando("reglas", "Muestra las reglas lógicas de conocimiento/reglas.kb y las estadísticas\n"
                           "del encadenamiento hacia adelante: hechos base y derivados, estratos e\n"
                           "iteraciones.")
    sp.set_defaults(func=cmd_reglas)

    sp = comando("escenarios", "Ejecuta 10 escenarios de uso con su resultado esperado (transbordos,\n"
                               "estaciones cerradas, ausencia de ruta, nombres sin tildes...) y guarda\n"
                               "la evidencia en un reporte Markdown.")
    sp.add_argument("--salida", default="resultados_pruebas.md",
                    help="archivo del reporte (por defecto resultados_pruebas.md)")
    sp.set_defaults(func=cmd_escenarios)
    return p


# ---------------------------------------------------------------------------
# Modo interactivo: menú principal y un submenú por actividad
# ---------------------------------------------------------------------------

ANCHO = 72                    # ancho de los encabezados y de las explicaciones del menú
FUENTES = {"real": "reales de TRANSMILENIO (2 al 29 de marzo de 2026)",
           "muestra": "muestra sintética (verdad conocida)"}
TIPOS_DIA = {"1": ("habil", "día hábil"), "2": ("sabado", "sábado"), "3": ("domingo_festivo", "domingo o festivo")}
CLASES = {"1": ("bajo", "bajo"), "2": ("medio", "medio"), "3": ("alto", "alto"), "4": ("", "todas")}
CONSULTA_PERFILES = "perfil_estacion(E, P), estacion_de_integracion(E)"
ELIJA = Text.assemble(("\n  Elija una opción ", "pregunta"), ("› ", "tecla"))


class Sesion:
    """Lo que comparten los menús: estaciones cerradas y fuente de datos de las Actividades 3 y 4."""

    def __init__(self) -> None:
        self.cerradas: List[str] = []
        self.datos = "real"

    def red(self) -> RedTransporte:
        return RedTransporte(cerradas=self.cerradas)

    def opcion_cerrar(self) -> List[str]:
        return ["--cerrar", *self.cerradas] if self.cerradas else []

    def opcion_datos(self) -> List[str]:
        return [] if self.datos == "real" else ["--datos", self.datos]

    def estado_cerradas(self) -> Text:
        valor = (", ".join(self.cerradas), "error") if self.cerradas else ("ninguna", "ok")
        return Text.assemble(("Estaciones cerradas: ", "nota"), valor)

    def estado_datos(self) -> Text:
        return Text.assemble(("Datos: ", "nota"), (FUENTES[self.datos], "ok" if self.datos == "real" else "aviso"))


@dataclass
class Opcion:
    tecla: str
    titulo: str
    descripcion: str
    accion: Callable[[Sesion], None]
    etiqueta: str = ""        # en el menú principal, la actividad: "Actividad 2"
    pausa: bool = True        # esperar Enter antes de volver a mostrar el menú


@dataclass
class Submenu:
    titulo: str
    subtitulo: str
    secciones: List[Tuple[str, List[Opcion]]]     # (nombre de la sección, sus opciones)
    estado: Callable[[Sesion], List[Text]]

    @property
    def opciones(self) -> List[Opcion]:
        return [o for _, opciones in self.secciones for o in opciones]


# --- presentación ------------------------------------------------------------

def _marco(titulo: str, lema: str) -> None:
    """Encabezado del menú principal: una franja roja con el nombre del sistema."""
    consola.print()
    consola.print(Panel(Group(Align.center(Text(titulo, style="bold")), Align.center(Text(lema))),
                        style="marca", box=box.SIMPLE, width=ANCHO))


def _titulo(texto: str, descripcion: str) -> None:
    """Encabezado de un submenú: el título en el borde y la descripción adentro."""
    consola.print()
    consola.print(Panel(Align.center(Text(descripcion, style="descripcion")), title=Text(texto, style="titulo"),
                        border_style="red", box=box.ROUNDED, width=ANCHO))


def _grilla_opciones(filas: Sequence[Tuple[str, Text, Text]], ancho_titulo: int) -> None:
    grilla = Table.grid(padding=(0, 2))
    grilla.add_column(justify="right", style="tecla")
    grilla.add_column(style="opcion", min_width=ancho_titulo)
    grilla.add_column(style="descripcion")
    for fila in filas:
        grilla.add_row(*fila)
    consola.print(Padding(grilla, (0, 0, 0, 3), expand=False))


def _mostrar_opciones(secciones: Sequence[Tuple[str, Sequence[Opcion]]], salida: str) -> None:
    """Opciones de un submenú, una por línea y agrupadas por sección. Todas las
    grillas usan el mismo ancho de título para que las columnas queden alineadas."""
    ancho = max(len(o.titulo) for _, opciones in secciones for o in opciones)
    for nombre, opciones in secciones:
        consola.print(Text(f"  {nombre.upper()}", style="seccion"))
        _grilla_opciones([(o.tecla, Text(o.titulo), Text(o.descripcion)) for o in opciones], ancho)
    consola.print()
    _grilla_opciones([("0", Text(salida, style="descripcion"), Text())], ancho)


def _mostrar_actividades(opciones: Sequence[Opcion]) -> None:
    """Menú principal: título y actividad en una línea y la descripción debajo."""
    ancho = max(len(o.titulo) for o in opciones)
    grilla = Table.grid(padding=(0, 2))
    grilla.add_column(justify="right", style="tecla")
    grilla.add_column()
    for o in opciones:
        grilla.add_row(o.tecla, Text.assemble((o.titulo.ljust(ancho), "opcion"), "  ", (o.etiqueta, "etiqueta"),
                                              "\n", (o.descripcion, "descripcion")))
        grilla.add_row()
    grilla.add_row("0", Text("Salir", style="descripcion"))
    consola.print(Padding(grilla, (0, 0, 0, 3), expand=False))


def _explicar(texto: Union[str, Text]) -> None:
    """Explicación breve de lo que hace una opción, antes de pedir los datos."""
    cuerpo = texto if isinstance(texto, Text) else Text(texto, style="descripcion")
    consola.print(Padding(cuerpo, (1, 2), expand=False), width=ANCHO)


def _equivalente(argumentos: Sequence[str]) -> None:
    partes = [a if re.fullmatch(r"[\w.:/\\-]+", a) else f'"{a}"' for a in argumentos]
    # soft_wrap: el comando sale en una sola línea, para copiarlo entero
    consola.print(Text.assemble(("\n  Comando equivalente: ", "nota"),
                                (f"python main.py {' '.join(partes)}", "comando")), soft_wrap=True)


def _ejecutar(argumentos: List[str]) -> None:
    """Ejecuta un comando de cualquier actividad, igual que desde la línea de comandos."""
    consola.print()
    if argumentos[0] in MODULOS_ACTIVIDAD:
        ejecutar_actividad(argumentos[0], argumentos[1:])
    else:
        args = construir_parser().parse_args(argumentos)
        args.func(args)
    _equivalente(argumentos)


# --- entradas ----------------------------------------------------------------

def _leer(mensaje: Union[str, Text]) -> str:
    consola.print(mensaje if isinstance(mensaje, Text) else Text(mensaje, style="pregunta"), end="")
    # Sin la marca BOM que agrega PowerShell al enviar texto por tubería al programa
    return input().replace("﻿", "").strip()


def _pedir_estacion(red: RedTransporte, mensaje: str) -> str:
    while True:
        try:
            return red.resolver_nombre(_leer(mensaje))
        except ValueError as e:
            aviso(str(e))


def _pedir_si_no(mensaje: str) -> bool:
    respuesta = _leer(Text.assemble((mensaje, "pregunta"), (" (s/N)", "nota"), ": "))
    return respuesta.lower().startswith("s")


def _pedir_entero(mensaje: str, minimo: int, maximo: int, opcional: bool = False,
                  por_defecto: Optional[int] = None) -> Optional[int]:
    """Entero entre minimo y maximo. Si es opcional, Enter devuelve por_defecto."""
    while True:
        texto = _leer(mensaje)
        if not texto and opcional:
            return por_defecto
        if texto.isdigit() and minimo <= int(texto) <= maximo:
            return int(texto)
        aviso(f"Escriba un número entre {minimo} y {maximo}.")


def _pedir_opcion(mensaje: str, opciones: Dict[str, Tuple[str, str]], por_defecto: str) -> str:
    """Elección numerada: muestra las opciones y devuelve el valor de la elegida."""
    linea = Text("    ")
    for tecla, (_, texto) in opciones.items():
        linea.append(tecla, style="tecla")
        linea.append(f" {texto}    ")
    consola.print(linea)
    while True:
        tecla = _leer(mensaje) or por_defecto
        if tecla in opciones:
            return opciones[tecla][0]
        aviso(f"Elija una de las opciones: {', '.join(opciones)}.")


def _pedir_momento() -> List[str]:
    """Hora, tipo de día y lluvia, como argumentos de los comandos de la Actividad 3."""
    hora = _pedir_entero("  Hora del día (4 a 22): ", 4, 22)
    dia = _pedir_opcion("  Tipo de día (Enter = día hábil): ", TIPOS_DIA, "1")
    lluvia = _pedir_si_no("  ¿Está lloviendo?")
    return ["--hora", str(hora), "--dia", dia] + (["--lluvia"] if lluvia else [])


def _pausa() -> None:
    _leer(Text("\n  Presione Enter para volver al menú...", style="nota"))


# --- Actividad 2 ---------------------------------------------------------------

def _a2_ruta(s: Sesion) -> None:
    _explicar("La búsqueda A* recorre la red que infiere la base de conocimiento y devuelve la "
              "ruta de menor tiempo, o la de menos transbordos si así lo pide.")
    red = s.red()
    origen = _pedir_estacion(red, "  Estación de origen: ")
    destino = _pedir_estacion(red, "  Estación de destino: ")
    criterio = ["-c", "transbordos"] if _pedir_si_no("  ¿Minimizar transbordos en lugar de tiempo?") else []
    _ejecutar(["ruta", origen, destino, "-d"] + criterio + s.opcion_cerrar())


def _a2_comparar(s: Sesion) -> None:
    _explicar("Ejecuta cuatro estrategias sobre el mismo viaje: dos no informadas (amplitud y costo "
              "uniforme) y dos informadas (voraz y A*). Compare el tiempo de la ruta y cuántos nodos "
              "exploró cada una.")
    red = s.red()
    origen = _pedir_estacion(red, "  Estación de origen: ")
    destino = _pedir_estacion(red, "  Estación de destino: ")
    criterio = ["-c", "transbordos"] if _pedir_si_no("  ¿Minimizar transbordos en lugar de tiempo?") else []
    _ejecutar(["comparar", origen, destino] + criterio + s.opcion_cerrar())


def _a2_consultar(s: Sesion) -> None:
    _explicar("Pregunte a la base de conocimiento: las variables van en mayúscula y las constantes "
              "entre comillas simples. Ejemplos: transbordo(E, T1, T2) · cabecera(E, T) · "
              "puede_abordar('Ricaurte', T) · estacion_de_integracion(E)")
    consulta = _leer("  Consulta (Enter = transbordo(E, T1, T2)): ") or "transbordo(E, T1, T2)"
    _ejecutar(["consultar", consulta] + s.opcion_cerrar())


def _a2_explicar(s: Sesion) -> None:
    _explicar("Muestra el árbol de prueba de un hecho: la regla que lo derivó y las premisas que usó. "
              "Escriba el predicado y sus argumentos; los nombres con espacios van entre comillas. "
              'Ejemplos: transbordo Ricaurte E F · estacion_de_integracion "Av. Jiménez"')
    texto = _leer("  Hecho (Enter = transbordo Ricaurte E F): ") or "transbordo Ricaurte E F"
    try:
        partes = shlex.split(texto)
    except ValueError:
        raise ValueError("Hay comillas sin cerrar en el hecho.") from None
    _ejecutar(["explicar", *partes] + s.opcion_cerrar())


def _a2_cerrar(s: Sesion) -> None:
    _explicar("Una estación cerrada se agrega a la base como el hecho cerrada(E): las reglas dejan de "
              "inferir movimientos por ella y todas las rutas se recalculan sin esa estación.")
    consola.print(Text.assemble("  ", s.estado_cerradas()))
    estacion = _pedir_estacion(s.red(), "  Estación a cerrar o reabrir: ")
    if estacion in s.cerradas:
        s.cerradas.remove(estacion)
        exito(f"{estacion} vuelve a estar habilitada.")
    else:
        s.cerradas.append(estacion)
        aviso(f'{estacion} queda cerrada: se agregó cerrada("{estacion}") a la base de hechos.')


def _a2_estaciones(s: Sesion) -> None:
    red = s.red()
    _explicar(Text.assemble(("Troncales:  ", "descripcion"), leyenda_troncales(red)))
    troncal = _leer("  Código de la troncal (Enter = todas las estaciones): ").upper()
    _ejecutar(["estaciones"] + (["--troncal", troncal] if troncal else []))


def _a2_reglas(s: Sesion) -> None:
    _ejecutar(["reglas"])


def _a2_escenarios(s: Sesion) -> None:
    _explicar("Ejecuta 10 escenarios de uso con su resultado esperado y guarda la evidencia en "
              "resultados_pruebas.md, en la carpeta desde la que se ejecuta el programa.")
    _ejecutar(["escenarios"])


# --- Actividad 3 ---------------------------------------------------------------

def _a3_explorar(s: Sesion) -> None:
    _ejecutar(["actividad3", "explorar"] + s.opcion_datos())


def _a3_entrenar(s: Sesion) -> None:
    _explicar("Divide los datos 70/30, elige la profundidad del árbol con validación cruzada de 5 "
              "pliegues, lo compara con ZeroR y OneR, y guarda el modelo, sus reglas y el reporte.")
    destino = "actividad3/resultados/" + ("" if s.datos == "real" else f"{s.datos}/")
    if not _pedir_si_no(f"  Tarda unos 11 s y reemplaza los archivos de {destino}. ¿Continuar?"):
        aviso("Entrenamiento cancelado.")
        return
    _ejecutar(["actividad3", "entrenar"] + s.opcion_datos())


def _a3_predecir(s: Sesion) -> None:
    _explicar("El árbol predice si la demanda de entradas será baja (menos de 250 por hora), media o "
              "alta (800 o más), y muestra la regla SI ... ENTONCES que lo explica.")
    estacion = _pedir_estacion(s.red(), "  Estación: ")
    _ejecutar(["actividad3", "predecir", "--estacion", estacion] + _pedir_momento() + s.opcion_datos())


def _a3_reglas(s: Sesion) -> None:
    _explicar("Cada hoja del árbol es una regla SI ... ENTONCES con su soporte (casos de "
              "entrenamiento que cubre) y su confianza. Se muestran las de mayor soporte.")
    clase = _pedir_opcion("  Clase (Enter = todas): ", CLASES, "4")
    cuantas = _pedir_entero("  ¿Cuántas reglas? (Enter = 10): ", 1, 1000, opcional=True, por_defecto=10)
    _ejecutar(["actividad3", "reglas", "--top", str(cuantas)] + (["--clase", clase] if clase else [])
              + s.opcion_datos())


def _a3_ruta(s: Sesion) -> None:
    _explicar("Calcula la ruta con A* (Actividad 2) y le pregunta al árbol qué demanda habrá en cada "
              "punto de abordaje. Si hay demanda alta, busca una hora de salida con menos congestión.")
    red = s.red()
    origen = _pedir_estacion(red, "  Estación de origen: ")
    destino = _pedir_estacion(red, "  Estación de destino: ")
    consola.print(Text("  Hora de salida:", style="nota"))
    _ejecutar(["actividad3", "ruta", origen, destino] + _pedir_momento() + s.opcion_cerrar()
              + s.opcion_datos())


def _cambiar_datos(s: Sesion) -> None:
    s.datos = "muestra" if s.datos == "real" else "real"
    consola.print(Text.assemble("  ", s.estado_datos(), "."))


# --- Actividad 4 ---------------------------------------------------------------

def _a4_explorar(s: Sesion) -> None:
    _ejecutar(["actividad4", "explorar"] + s.opcion_datos())


def _a4_codo(s: Sesion) -> None:
    _explicar("Para k = 2 a 8 grupos calcula la suma de errores cuadráticos (método del codo) y el "
              "coeficiente de silueta de k-medias y de Ward. Guarda codo.svg y silueta.svg.")
    _ejecutar(["actividad4", "codo"] + s.opcion_datos())


def _a4_agrupar(s: Sesion) -> None:
    _explicar("Agrupa las estaciones con k-medias y con Ward, nombra cada grupo según su centroide y "
              "guarda el reporte, los mapas y los hechos perfiles.kb. Con un k fijo, los resultados van "
              "a la carpeta resultados/kN/.")
    k = _pedir_entero("  Número de grupos k (Enter = el de mejor silueta): ", 2, 20, opcional=True)
    _ejecutar(["actividad4", "agrupar"] + (["-k", str(k)] if k else []) + s.opcion_datos())


def _archivos_perfiles(datos: str) -> List[Tuple[str, str]]:
    """(ruta relativa a la raíz, descripción) de cada perfiles.kb generado por la Actividad 4."""
    base = "actividad4/resultados" + ("" if datos == "real" else f"/{datos}")
    carpeta = os.path.join(DIR_RAIZ, *base.split("/"))
    archivos = []
    if os.path.exists(os.path.join(carpeta, "perfiles.kb")):
        archivos.append((f"{base}/perfiles.kb", "k elegido por la silueta"))
    if os.path.isdir(carpeta):
        for nombre in sorted(os.listdir(carpeta), key=lambda n: (len(n), n)):
            if re.fullmatch(r"k\d+", nombre) and os.path.exists(os.path.join(carpeta, nombre, "perfiles.kb")):
                archivos.append((f"{base}/{nombre}/perfiles.kb", f"k = {nombre[1:]}, fijado con -k"))
    return archivos


def _a4_perfiles(s: Sesion) -> None:
    _explicar("Los grupos de la Actividad 4 se exportan como hechos perfil_estacion(E, P). Aquí se cargan "
              "en la base de conocimiento de la Actividad 2 y se consultan junto con sus reglas. "
              "Ejemplos: perfil_estacion(E, P) · perfil_estacion(E, P), portal(E)")
    archivos = _archivos_perfiles(s.datos)
    if not archivos:
        aviso("Todavía no hay perfiles: use primero la opción 3 (Agrupar las estaciones).")
        return
    ruta = archivos[0][0]
    if len(archivos) > 1:
        elegido = _pedir_opcion("  Agrupamiento (Enter = 1): ",
                                {str(i): (r, d) for i, (r, d) in enumerate(archivos, 1)}, "1")
        ruta = elegido
    consulta = _leer("  Consulta (Enter = perfil de las estaciones de integración): ") or CONSULTA_PERFILES
    _ejecutar(["consultar", consulta, "--con", ruta] + s.opcion_cerrar())


# --- menús -----------------------------------------------------------------------

def _submenus() -> Dict[str, Submenu]:
    return {
        "2": Submenu(
            "ACTIVIDAD 2 · Rutas óptimas",
            "Base de conocimiento (conocimiento/) + búsqueda A* (sistema/)",
            [("Búsqueda de rutas", [
                Opcion("1", "Buscar la mejor ruta", "Pasos, tiempo y transbordos con A*", _a2_ruta),
                Opcion("2", "Comparar algoritmos de búsqueda", "Amplitud, costo uniforme, voraz y A*",
                       _a2_comparar)]),
             ("Base de conocimiento", [
                 Opcion("3", "Consultar la base de conocimiento", "Preguntas lógicas, ej. cabecera(E, T)",
                        _a2_consultar),
                 Opcion("4", "Explicar una conclusión", "Reglas y hechos que la demuestran", _a2_explicar)]),
             ("Red de estaciones", [
                 Opcion("5", "Cerrar o reabrir una estación", "Las rutas se recalculan sin ella", _a2_cerrar,
                        pausa=False),
                 Opcion("6", "Ver estaciones y troncales", "Todas, o una troncal en orden", _a2_estaciones)]),
             ("Reglas y pruebas", [
                 Opcion("7", "Ver las reglas del sistema", "Las 15 reglas y las estadísticas",
                        _a2_reglas),
                 Opcion("8", "Ejecutar los escenarios de prueba", "10 casos; genera resultados_pruebas.md",
                        _a2_escenarios)])],
            lambda s: [s.estado_cerradas()]),
        "3": Submenu(
            "ACTIVIDAD 3 · Demanda en las estaciones",
            "Árbol de decisión ID3/C4.5 · aprendizaje supervisado",
            [("Datos y modelo", [
                Opcion("1", "Explorar los datos", "Demanda por franja, día y estación", _a3_explorar),
                Opcion("2", "Entrenar el árbol de decisión", "Validación cruzada y métricas (~11 s)",
                       _a3_entrenar)]),
             ("Usar el modelo", [
                 Opcion("3", "Predecir la demanda de una estación", "Baja, media o alta, con su regla",
                        _a3_predecir),
                 Opcion("4", "Ver las reglas del modelo", "Reglas SI … ENTONCES con más soporte", _a3_reglas),
                 Opcion("5", "Ruta con demanda prevista", "Ruta A* y demanda en cada abordaje", _a3_ruta)]),
             ("Configuración", [
                 Opcion("6", "Cambiar la fuente de datos", "Datos reales o muestra sintética", _cambiar_datos,
                        pausa=False)])],
            lambda s: [s.estado_datos(), s.estado_cerradas()]),
        "4": Submenu(
            "ACTIVIDAD 4 · Tipos de estación",
            "k-medias y Ward · aprendizaje no supervisado",
            [("Agrupamiento", [
                Opcion("1", "Explorar los perfiles de uso", "Atributos de uso y perfil horario",
                       _a4_explorar),
                Opcion("2", "Elegir el número de grupos", "Codo y silueta para k = 2 a 8", _a4_codo),
                Opcion("3", "Agrupar las estaciones", "k-medias y Ward; reporte y perfiles.kb",
                       _a4_agrupar)]),
             ("Base de conocimiento", [
                 Opcion("4", "Consultar los perfiles de estación", "perfiles.kb + reglas de la Actividad 2",
                        _a4_perfiles)]),
             ("Configuración", [
                 Opcion("5", "Cambiar la fuente de datos", "Datos reales o muestra sintética", _cambiar_datos,
                        pausa=False)])],
            lambda s: [s.estado_datos()]),
    }


def _correr(opcion: Opcion, sesion: Sesion) -> None:
    consola.print()
    consola.print(Rule(Text(f"{opcion.tecla} · {opcion.titulo}", style="opcion"), align="left", style="borde"))
    try:
        opcion.accion(sesion)
    except (ValueError, ErrorLogico) as e:
        consola.print()
        error(str(e))
    except SystemExit:
        pass                  # argparse de las Actividades 3 y 4 ya explicó el problema
    except KeyboardInterrupt:
        consola.print()
        aviso("Operación cancelada.")
    if opcion.pausa:
        _pausa()


def _menu(sesion: Sesion, submenu: Submenu) -> None:
    """Submenú de una actividad: se repite hasta que se elige 0."""
    while True:
        _titulo(submenu.titulo, submenu.subtitulo)
        for linea in submenu.estado(sesion):
            consola.print(Text.assemble("  ", linea))
        consola.print()
        _mostrar_opciones(submenu.secciones, "Volver al menú principal")
        eleccion = _leer(ELIJA)
        if eleccion == "0":
            return
        opcion = next((o for o in submenu.opciones if o.tecla == eleccion), None)
        if opcion is None:
            aviso("Opción no válida.")
            continue
        _correr(opcion, sesion)


def modo_interactivo() -> None:
    sesion = Sesion()
    submenus = _submenus()
    principal = [
        Opcion("2", "Rutas óptimas", "Base de conocimiento, motor de inferencia y búsqueda A*.",
               lambda s: _menu(s, submenus["2"]), etiqueta="Actividad 2"),
        Opcion("3", "Demanda en las estaciones",
               "Árbol de decisión entrenado con datos reales de TRANSMILENIO.",
               lambda s: _menu(s, submenus["3"]), etiqueta="Actividad 3"),
        Opcion("4", "Tipos de estación",
               "k-medias y Ward descubren tipos de estación según su uso.",
               lambda s: _menu(s, submenus["4"]), etiqueta="Actividad 4"),
    ]
    try:
        while True:
            _marco("SISTEMA INTELIGENTE DE RUTAS EN TRANSMILENIO", "Inteligencia Artificial · Actividades 2, 3 y 4")
            consola.print(Text("\n  ¿Qué desea hacer?\n", style="pregunta"))
            _mostrar_actividades(principal)
            eleccion = _leer(ELIJA)
            if eleccion == "0":
                break
            opcion = next((o for o in principal if o.tecla == eleccion), None)
            if opcion is None:
                aviso("Opción no válida.")
                continue
            opcion.accion(sesion)
    except (KeyboardInterrupt, EOFError):
        consola.print()
    consola.print(Text("\n  Hasta luego.", style="opcion"))


# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    _utf8_en_consola()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in MODULOS_ACTIVIDAD:
        return ejecutar_actividad(argv[0], argv[1:])
    args = construir_parser().parse_args(argv)
    if not args.comando:
        modo_interactivo()
        return 0
    try:
        args.func(args)
        return 0
    except (ValueError, ErrorLogico) as e:
        error(str(e), stderr=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
