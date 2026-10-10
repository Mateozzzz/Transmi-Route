"""
Actividad 3 - Aprendizaje supervisado sobre la red de TransMilenio.

Problema: dado el momento (hora, tipo de día, lluvia) y las características de
una estación (portal, integración, troncales, ubicación), predecir el NIVEL DE
DEMANDA de entradas en esa hora: bajo, medio o alto. Se usa un árbol de
decisión (ID3/C4.5) y se extraen sus reglas SI ... ENTONCES ....

Uso:
    python -m actividad3 importar                     # descarga y convierte los datos reales (marzo de 2026)
    python -m actividad3 generar                      # crea la muestra sintética en /datos
    python -m actividad3 explorar                     # análisis exploratorio
    python -m actividad3 entrenar                     # validación cruzada, entrenamiento y reporte
    python -m actividad3 reglas [--clase alto]        # reglas del modelo guardado
    python -m actividad3 predecir --estacion "Portal Norte" --hora 7 --dia habil
    python -m actividad3 ruta "Portal Norte" "Av. Jiménez" --hora 7 --dia habil

Por defecto se usan los datos reales; con --datos muestra, la muestra sintética
(sus resultados se guardan aparte, en resultados/muestra/).
"""
from __future__ import annotations

import argparse
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from aprendizaje import graficos
from aprendizaje.arbol import ArbolDecision, OneR, ReglaDecision, ZeroR
from aprendizaje.datos import (DESCRIPCION_DATOS, FACTOR_TIPO_DIA, HORAS, NOMBRE_DATOS, RUTA_VALIDACIONES,
                               RUTAS_DATOS, atributos_estaciones, cargar_dataset, generar_archivos, unir_atributos)
from aprendizaje.datos_reales import agregar_opciones_importar
from aprendizaje.evaluacion import calcular_metricas, division_estratificada, validar_profundidad
from aprendizaje.salida import escribir, pct, ruta_relativa, tabla_md, utf8_en_consola
from sistema.busqueda import buscar_ruta
from sistema.consola import (Group, Panel, RegexHighlighter, Table, Text, aviso, box, consola, encabezado, error,
                             exito, pares, subtitulo, tabla_rich)
from sistema.logica import ErrorLogico
from sistema.presentacion import panel_ruta
from sistema.red import RedTransporte

DIR_ACTIVIDAD = os.path.dirname(os.path.abspath(__file__))


def dir_resultados(datos: str) -> str:
    """Datos reales -> resultados/ ; muestra sintética -> resultados/muestra/."""
    base = os.path.join(DIR_ACTIVIDAD, "resultados")
    return base if datos == "real" else os.path.join(base, datos)


def ruta_modelo(datos: str) -> str:
    return os.path.join(dir_resultados(datos), "modelo_arbol.json")

# Etiqueta: entradas por hora en la estación
UMBRAL_MEDIO, UMBRAL_ALTO = 250, 800
CLASES = ["bajo", "medio", "alto"]

# Franjas horarias (aproximan las horas pico de TransMilenio)
FRANJAS = [("madrugada", 4, 5), ("pico_am", 6, 8), ("valle", 9, 15), ("pico_pm", 16, 19), ("noche", 20, 22)]
ATRIBUTOS = ["hora", "franja", "tipo_dia", "lluvia", "es_portal", "es_integracion", "num_troncales",
             "distancia_centro_km", "latitud", "longitud"]
SEMILLA = 42


def nivel_demanda(entradas: int) -> str:
    if entradas >= UMBRAL_ALTO:
        return "alto"
    return "medio" if entradas >= UMBRAL_MEDIO else "bajo"


def franja(hora: int) -> str:
    for nombre, desde, hasta in FRANJAS:
        if desde <= hora <= hasta:
            return nombre
    raise ValueError(f"Hora fuera del horario de operación ({HORAS[0]}-{HORAS[-1]}): {hora}")


def ejemplo(atributos_estacion: Dict[str, object], hora: int, tipo_dia: str, lluvia: bool) -> Dict[str, object]:
    """Vector de atributos de una estación en un momento dado (lo que ve el árbol)."""
    x = {a: atributos_estacion[a] for a in ATRIBUTOS if a in atributos_estacion}
    x.update(hora=hora, franja=franja(hora), tipo_dia=tipo_dia, lluvia="si" if lluvia else "no")
    return x


def preparar(filas: Sequence[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[str]]:
    """Ingeniería de atributos + etiqueta. Las filas ya vienen unidas con el catálogo."""
    X = [{**{a: f[a] for a in ATRIBUTOS if a != "franja"}, "franja": franja(f["hora"])} for f in filas]
    y = [nivel_demanda(f["entradas"]) for f in filas]
    return X, y


def _cargar(red: RedTransporte, datos: str) -> List[Dict[str, object]]:
    return unir_atributos(cargar_dataset(RUTAS_DATOS[datos]), atributos_estaciones(red))


def _opcion_datos(datos: str) -> str:
    return "" if datos == "real" else f" --datos {datos}"


def _cargar_modelo(datos: str) -> ArbolDecision:
    if not os.path.exists(ruta_modelo(datos)):
        raise ValueError(f"No hay un modelo entrenado ({NOMBRE_DATOS[datos]}). "
                         f"Ejecute: python -m actividad3 entrenar{_opcion_datos(datos)}")
    with open(ruta_modelo(datos), encoding="utf-8") as f:
        return ArbolDecision.desde_json(f.read())


def _hora(texto: str) -> float:
    """'7' -> 7.0 ; '7:30' -> 7.5"""
    try:
        if ":" in texto:
            h, m = texto.split(":")
            return int(h) + int(m) / 60
        return float(texto)
    except ValueError:
        raise ValueError(f"Hora inválida: {texto!r} (use 7 o 7:30)") from None


# ---------------------------------------------------------------------------
# Presentación en la consola
# ---------------------------------------------------------------------------

class ResaltadorDecision(RegexHighlighter):
    """Colores para las reglas SI ... ENTONCES y el árbol en texto: palabras clave y clases."""
    base_style = "arbol."
    highlights = [
        r"(?P<conector>[├└│─]+)",
        r"\b(?P<clave>SI|Y|ENTONCES)\b",
        r"\b(?P<bajo>bajo)\b",
        r"\b(?P<medio>medio)\b",
        r"\b(?P<alto>alto)\b",
    ]


resaltar = ResaltadorDecision()


def _clase(clase: str, mayusculas: bool = False) -> Text:
    """Nombre de la clase con el color de su nivel de demanda."""
    return Text(clase.upper() if mayusculas else clase, style=f"nivel.{clase}")


def _entonces(regla: ReglaDecision) -> Text:
    return Text.assemble(("ENTONCES ", "arbol.clave"), _clase(regla.clase),
                         (f"  · soporte {regla.soporte} · confianza {regla.confianza:.0%}", "nota"))


def _tabla_reglas(reglas: Sequence[Tuple[Text, ReglaDecision]]) -> Table:
    """Cada regla en dos líneas, SI ... y debajo ENTONCES clase, con una línea en blanco entre reglas."""
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="tecla", no_wrap=True)
    t.add_column()
    for i, (etiqueta, r) in enumerate(reglas):
        if i:
            t.add_row()
        t.add_row(etiqueta, Group(resaltar(f"SI {r.texto_condiciones()}"), _entonces(r)))
    return t


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_generar(args) -> None:
    filas, estaciones = generar_archivos(args.dias, args.semilla)
    exito(f"Dataset generado: {filas} filas ({estaciones} estaciones × {len(HORAS)} horas × {args.dias} días)")
    consola.print(Text(f"    {ruta_relativa(RUTA_VALIDACIONES, os.getcwd())}", style="nota"))
    consola.print(Text("    datos/estaciones.csv  (atributos derivados de la base de conocimiento)", style="nota"))


def cmd_explorar(args) -> None:
    red = RedTransporte()
    filas = _cargar(red, args.datos)
    fechas = sorted({f["fecha"] for f in filas})
    encabezado(f"Dataset de afluencia ({NOMBRE_DATOS[args.datos]})")
    consola.print(pares([
        ("Filas", len(filas)),
        ("Estaciones", len({f["estacion"] for f in filas})),
        ("Días", f"{len(fechas)} ({fechas[0]} a {fechas[-1]})"),
        ("Horas", f"{HORAS[0]}:00-{HORAS[-1]}:59"),
        ("Tipo de día", " · ".join(f"{t} {n}" for t, n in sorted(Counter(f["tipo_dia"] for f in filas).items()))),
        ("Horas con lluvia", pct(sum(f["lluvia"] == "si" for f in filas) / len(filas))),
        ("Columnas", ", ".join(filas[0].keys())),
    ]))

    entradas = sorted(f["entradas"] for f in filas)
    q = statistics.quantiles(entradas, n=4)
    subtitulo("Entradas por estación-hora")
    consola.print(tabla_rich(["Mín", "Q1", "Mediana", "Q3", "Máx", "Media"],
                             [[entradas[0], f"{q[0]:.0f}", f"{q[1]:.0f}", f"{q[2]:.0f}", entradas[-1],
                               f"{statistics.mean(entradas):.0f}"]]))
    _, y = preparar(filas)
    conteo = Counter(y)
    subtitulo(f"Etiqueta nivel_demanda (bajo < {UMBRAL_MEDIO} ≤ medio < {UMBRAL_ALTO} ≤ alto)")
    consola.print(tabla_rich(["Clase", "Ejemplos", "%"],
                             [[_clase(c), conteo[c], pct(conteo[c] / len(y))] for c in CLASES]))

    subtitulo("Entradas promedio por franja y tipo de día")
    acum: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for f in filas:
        acum[(franja(f["hora"]), f["tipo_dia"])].append(f["entradas"])
    tipos = list(FACTOR_TIPO_DIA)
    consola.print(tabla_rich(["Franja"] + tipos, [[n] + [f"{statistics.mean(acum[(n, t)]):.0f}" for t in tipos]
                                                  for n, _, _ in FRANJAS]))

    subtitulo("Estaciones con más entradas en un día hábil promedio")
    por_estacion: Dict[str, int] = defaultdict(int)
    dias_habiles = len({f["fecha"] for f in filas if f["tipo_dia"] == "habil"})
    for f in filas:
        if f["tipo_dia"] == "habil":
            por_estacion[f["estacion"]] += f["entradas"]
    top = sorted(por_estacion.items(), key=lambda kv: -kv[1])[: args.top]
    atrib = atributos_estaciones(red)
    consola.print(tabla_rich(["Estación", "Entradas/día", "Portal", "Integración"],
                             [[Text(e, style="estacion"), f"{v / dias_habiles:,.0f}".replace(",", "."),
                               atrib[e]["es_portal"], atrib[e]["es_integracion"]] for e, v in top]))


def cmd_entrenar(args) -> None:
    t0 = time.perf_counter()
    red = RedTransporte()
    filas = _cargar(red, args.datos)
    directorio = dir_resultados(args.datos)
    X, y = preparar(filas)
    idx_ent, idx_pru = division_estratificada(y, 0.3, SEMILLA)
    X_ent, y_ent = [X[i] for i in idx_ent], [y[i] for i in idx_ent]
    X_pru, y_pru = [X[i] for i in idx_pru], [y[i] for i in idx_pru]
    parametros = dict(criterio=args.criterio, min_muestras_hoja=args.min_hoja)
    encabezado("Entrenamiento del árbol de decisión", NOMBRE_DATOS[args.datos])
    consola.print(pares([
        ("Ejemplos", f"{len(X)}: entrenamiento {len(X_ent)} / prueba {len(X_pru)} (estratificado 70/30)"),
        ("Atributos", ", ".join(ATRIBUTOS)),
    ]))

    curva = []
    if args.profundidad:
        elegida = args.profundidad
        consola.print(Text.assemble(("Profundidad fijada por el usuario: ", "nota"), (str(elegida), "dato")))
    else:
        with consola.status(f"Validación cruzada estratificada ({args.pliegues} pliegues), "
                            f"profundidad 1..{args.max_prof} ..."):
            curva, elegida = validar_profundidad(X_ent, y_ent, ATRIBUTOS, range(1, args.max_prof + 1),
                                                 args.pliegues, SEMILLA, **parametros)
        subtitulo(f"Validación cruzada estratificada ({args.pliegues} pliegues)")
        consola.print(tabla_rich(["Prof.", "Exactitud entren.", "Exactitud valid.", "Error est."],
                                 [[p.profundidad, pct(p.exactitud_entrenamiento), pct(p.exactitud_validacion),
                                   pct(p.error_estandar, 2)] for p in curva],
                                 estilos_fila=["resumen" if p.profundidad == elegida else None for p in curva]))
        consola.print(Text.assemble(("Profundidad elegida (regla de 1 error estándar): ", "nota"),
                                    (str(elegida), "resumen")))

    arbol = ArbolDecision(profundidad_max=elegida, **parametros).entrenar(X_ent, y_ent, ATRIBUTOS, clases=CLASES)
    zeror = ZeroR().entrenar(X_ent, y_ent)
    oner = OneR().entrenar(X_ent, y_ent, ATRIBUTOS, arbol.tipos)
    modelos = [("ZeroR (clase mayoritaria)", zeror.predecir_lote(X_pru)),
               (f"OneR (atributo '{oner.atributo}')", oner.predecir_lote(X_pru)),
               (f"Árbol de decisión (prof. {elegida})", arbol.predecir_lote(X_pru))]
    metricas = [(n, calcular_metricas(y_pru, p, CLASES)) for n, p in modelos]
    m_arbol = metricas[-1][1]
    nodos, hojas, prof_real = arbol.contar()
    reglas = arbol.extraer_reglas()

    consola.print(Text.assemble(("Árbol: ", "nota"),
                                f"{nodos} nodos, {hojas} hojas (= reglas), profundidad {prof_real}"))
    subtitulo("Resultados en el conjunto de PRUEBA")
    consola.print(tabla_rich(["Modelo", "Exactitud", "F1 macro"],
                             [[n, pct(m.exactitud), f"{m.f1_macro:.3f}"] for n, m in metricas],
                             estilos_fila=[None] * (len(metricas) - 1) + ["resumen"]))
    subtitulo("Métricas por clase (árbol)")
    consola.print(tabla_rich(["Clase", "Precisión", "Exhaustividad", "F1", "Soporte"],
                             [[_clase(c), f"{v['precision']:.3f}", f"{v['recall']:.3f}", f"{v['f1']:.3f}",
                               v["soporte"]] for c, v in m_arbol.por_clase.items()]))
    subtitulo("Matriz de confusión (filas = real, columnas = predicha; en verde, los aciertos)")
    consola.print(tabla_rich(["real \\ pred"] + CLASES,
                             [[_clase(c)] + [Text(str(v), style="ok" if i == j else "") for j, v in enumerate(fila)]
                              for i, (c, fila) in enumerate(zip(CLASES, m_arbol.matriz))]))
    importancia = arbol.importancia()
    subtitulo("Importancia de los atributos")
    mayor = max(importancia.values(), default=0) or 1
    consola.print(tabla_rich(["Atributo", "Importancia", ""],
                             [[a, pct(v), Text("█" * round(v / mayor * 30), style="chispa")]
                              for a, v in importancia.items()]))
    subtitulo("Primeros niveles del árbol")
    consola.print(Panel(resaltar(arbol.a_texto(profundidad_max=3)), border_style="borde", box=box.ROUNDED,
                        expand=False))
    subtitulo("Reglas con mayor soporte por clase")
    consola.print(_tabla_reglas([(Text("●", style=f"nivel.{c}"), r)
                                 for c in CLASES for r in [r for r in reglas if r.clase == c][:3]]))

    # --- archivos de resultados ---
    os.makedirs(directorio, exist_ok=True)
    escribir(ruta_modelo(args.datos), arbol.a_json())
    escribir(os.path.join(directorio, "reglas.txt"),
             f"# {len(reglas)} reglas extraídas del árbol (una por hoja)\n" + "\n".join(map(str, reglas)) + "\n")
    escribir(os.path.join(directorio, "arbol.txt"), arbol.a_texto() + "\n")
    graficos.guardar(graficos.barras_horizontales(
        list(importancia), [v * 100 for v in importancia.values()], "Importancia de los atributos",
        "Ganancia de información aportada por cada atributo en el árbol (% del total)",
        formato=lambda v: f"{v:.1f} %"), os.path.join(directorio, "importancia_atributos.svg"))
    if curva:
        graficos.guardar(graficos.lineas(
            [p.profundidad for p in curva],
            {"Entrenamiento": [p.exactitud_entrenamiento * 100 for p in curva],
             "Validación": [p.exactitud_validacion * 100 for p in curva]},
            "Exactitud según la profundidad del árbol",
            f"Validación cruzada estratificada de {args.pliegues} pliegues sobre el conjunto de entrenamiento",
            "profundidad máxima del árbol", "exactitud (%)", marcar_x=elegida,
            texto_marca=f"elegida: {elegida}", formato_y=lambda v: f"{v:g}"),
            os.path.join(directorio, "curva_profundidad.svg"))
    reporte = _reporte(filas, y, args, curva, elegida, metricas, oner, arbol, reglas, importancia, red)
    escribir(os.path.join(directorio, "reporte.md"), reporte)
    consola.print()
    exito(f"Modelo, reglas, gráficos y reporte guardados en {ruta_relativa(directorio, os.getcwd())}/ "
          f"({time.perf_counter() - t0:.1f} s)")


def _reporte(filas, y, args, curva, elegida, metricas, oner, arbol, reglas, importancia, red) -> str:
    conteo = Counter(y)
    fechas = sorted({f["fecha"] for f in filas})
    m_arbol = metricas[-1][1]
    nodos, hojas, prof_real = arbol.contar()
    md = [
        "# Resultados - Actividad 3: árbol de decisión de demanda en TransMilenio", "",
        f"Generado el {date.today():%Y-%m-%d} con `python -m actividad3 entrenar{_opcion_datos(args.datos)}"
        + (f" --profundidad {args.profundidad}" if args.profundidad else "")
        + (f" --criterio {args.criterio}" if args.criterio != "ganancia" else "") + "`.", "",
        "## Datos", "",
        f"- Fuente: {DESCRIPCION_DATOS[args.datos]}.",
        f"- {len(filas)} ejemplos (estación × hora) del {fechas[0]} al {fechas[-1]}, "
        f"{len({f['estacion'] for f in filas})} estaciones.",
        f"- Etiqueta `nivel_demanda`: bajo (< {UMBRAL_MEDIO} entradas/h), medio ({UMBRAL_MEDIO}-{UMBRAL_ALTO - 1}), "
        f"alto (≥ {UMBRAL_ALTO}).", "",
        tabla_md(["Clase", "Ejemplos", "%"], [[c, conteo[c], pct(conteo[c] / len(y))] for c in CLASES]), "",
        f"- Atributos: {', '.join(f'`{a}`' for a in ATRIBUTOS)}.",
        f"- Criterio de división: **{'ganancia de información (ID3)' if args.criterio == 'ganancia' else 'razón de ganancia (C4.5)'}**, "
        f"mínimo {args.min_hoja} ejemplos por hoja.",
        "- Partición estratificada: 70 % entrenamiento, 30 % prueba (semilla 42).", "",
    ]
    if curva:
        md += ["## Selección de la profundidad (validación cruzada)", "",
               f"Validación cruzada estratificada de {args.pliegues} pliegues. Se elige la profundidad más pequeña "
               "cuya exactitud está a menos de un error estándar de la mejor.", "",
               "![Curva de profundidad](curva_profundidad.svg)", "",
               tabla_md(["Profundidad", "Exactitud entrenamiento", "Exactitud validación"],
                        [[p.profundidad, pct(p.exactitud_entrenamiento), pct(p.exactitud_validacion)]
                         for p in curva]), "",
               f"**Profundidad elegida: {elegida}.**", ""]
    md += ["## Resultados en el conjunto de prueba", "",
           tabla_md(["Modelo", "Exactitud", "F1 macro"],
                    [[n, pct(m.exactitud), f"{m.f1_macro:.3f}"] for n, m in metricas]), "",
           f"El árbol tiene {nodos} nodos y {hojas} hojas (= {hojas} reglas), profundidad real {prof_real}.", "",
           "### Métricas por clase (árbol)", "",
           tabla_md(["Clase", "Precisión", "Exhaustividad", "F1", "Soporte"],
                    [[c, f"{v['precision']:.3f}", f"{v['recall']:.3f}", f"{v['f1']:.3f}", v["soporte"]]
                     for c, v in m_arbol.por_clase.items()]), "",
           "### Matriz de confusión (filas = real, columnas = predicha)", "",
           tabla_md(["real \\ predicha"] + CLASES, [[f"**{c}**"] + fila for c, fila in zip(CLASES, m_arbol.matriz)]), "",
           "## Importancia de los atributos", "",
           "![Importancia de los atributos](importancia_atributos.svg)", "",
           tabla_md(["Atributo", "Importancia"], [[f"`{a}`", pct(v)] for a, v in importancia.items()]), "",
           "## Primeros niveles del árbol", "",
           "```mermaid", arbol.a_mermaid(2), "```", "",
           "```text", arbol.a_texto(profundidad_max=3), "```", "",
           "El árbol completo está en [arbol.txt](arbol.txt).", "",
           "## Reglas de decisión", "",
           f"Cada hoja del árbol es una regla. Se muestran las 5 de mayor soporte por clase; "
           f"las {len(reglas)} reglas están en [reglas.txt](reglas.txt).", ""]
    for c in CLASES:
        md += [f"**{c.capitalize()}**", "", "```text"] + [str(r) for r in reglas if r.clase == c][:5] + ["```", ""]
    md += ["### Línea base OneR", "", f"OneR elige el atributo `{oner.atributo}`:", "", "```text",
           *oner.describir(), "```", "",
           "## Ejemplos de predicción explicada", ""]
    atrib = atributos_estaciones(red)
    casos = [("Portal Norte", 6, "habil", False), ("Calle 100", 18, "habil", False),
             ("U. Nacional", 13, "sabado", False), ("Calle 45", 21, "domingo_festivo", True)]
    for est, h, td, ll in casos:
        regla = arbol.explicar(ejemplo(atrib[est], h, td, ll))
        md.append(f"- **{est}**, {h}:00, {td}{', con lluvia' if ll else ''} → **{regla.clase}** "
                  f"({regla.confianza:.0%} de {regla.soporte} casos). Regla: `{regla.texto_condiciones()}`")
    md.append("")
    return "\n".join(md)


def cmd_reglas(args) -> None:
    arbol = _cargar_modelo(args.datos)
    reglas = [r for r in arbol.extraer_reglas() if not args.clase or r.clase == args.clase]
    mostradas = reglas[: args.top] if args.top else reglas
    consola.print(_tabla_reglas([(Text(f"R{i}"), r) for i, r in enumerate(mostradas, 1)]))
    resumen = f"{len(reglas)} regla(s){' de clase ' + args.clase if args.clase else ''}"
    if len(mostradas) < len(reglas):
        resumen += f"; se muestran las {len(mostradas)} de mayor soporte"
    consola.print()
    consola.print(Text(resumen + ".", style="nota"))


def _promedio_observado(filas, estacion: str, hora: int, tipo_dia: str) -> Optional[float]:
    valores = [f["entradas"] for f in filas
               if f["estacion"] == estacion and f["hora"] == hora and f["tipo_dia"] == tipo_dia]
    return statistics.mean(valores) if valores else None


def cmd_predecir(args) -> None:
    arbol = _cargar_modelo(args.datos)
    red = RedTransporte()
    est = red.resolver_nombre(args.estacion)
    hora = int(_hora(args.hora))
    x = ejemplo(atributos_estaciones(red)[est], hora, args.dia, args.lluvia)
    regla = arbol.explicar(x)
    cuerpo: List[object] = [
        Text.assemble("Nivel de demanda previsto: ", _clase(regla.clase, mayusculas=True)),
        Text(),
        Text("Regla aplicada:", style="nota"),
        resaltar(f"SI {regla.texto_condiciones()}"),
        Text.assemble(("ENTONCES ", "arbol.clave"), _clase(regla.clase),
                      (f"  [cubre {regla.soporte} ejemplos de entrenamiento, confianza {regla.confianza:.0%}]",
                       "nota")),
    ]
    if os.path.exists(RUTAS_DATOS[args.datos]):
        prom = _promedio_observado(cargar_dataset(RUTAS_DATOS[args.datos]), est, hora, args.dia)
        cuerpo.append(Text())
        if prom is not None:
            cuerpo.append(Text.assemble(f"Promedio observado ({NOMBRE_DATOS[args.datos]}): {prom:.0f} entradas/h "
                                        "(nivel ", _clase(nivel_demanda(round(prom))), ")."))
        else:
            cuerpo.append(Text(f"La estación no tiene observaciones ({NOMBRE_DATOS[args.datos]}): "
                               "la predicción sale solo de sus atributos.", style="aviso"))
    cuerpo += [Text(), Text("Atributos: " + ", ".join(f"{k}={v}" for k, v in x.items()), style="nota")]
    consola.print(Panel(Group(*cuerpo), box=box.ROUNDED, border_style="borde", expand=False, padding=(0, 2),
                        title=Text(f"Predicción: {est}, {hora}:00, día {args.dia}"
                                   f"{', con lluvia' if args.lluvia else ''}", style="titulo"), title_align="left"))


def _abordajes(r, hora_salida: float) -> List[Tuple[str, str, float]]:
    """(acción, estación, hora estimada) de cada abordaje o transbordo de la ruta."""
    eventos, transcurrido = [], 0.0
    for p in r.pasos:
        if p.accion in ("abordar", "transbordo"):
            eventos.append((p.accion, p.desde, hora_salida + transcurrido / 60))
        transcurrido += p.minutos
    return eventos


def _hora_texto(h: float) -> str:
    total = int(round(h * 60))
    return f"{total // 60:02d}:{total % 60:02d}"


def _hora_modelo(h: float) -> int:
    return min(max(int(h), HORAS[0]), HORAS[-1])


def cmd_ruta(args) -> None:
    arbol = _cargar_modelo(args.datos)
    red = RedTransporte(cerradas=args.cerrar or [])
    atrib = atributos_estaciones(red)
    r = buscar_ruta(red, args.origen, args.destino, "a_estrella", args.criterio)
    consola.print(panel_ruta(red, r))
    if not r.encontrado or not r.pasos:
        return
    salida = _hora(args.hora)
    filas = []
    for accion, est, h in _abordajes(r, salida):
        regla = arbol.explicar(ejemplo(atrib[est], _hora_modelo(h), args.dia, args.lluvia))
        filas.append([accion, Text(est, style="estacion"), _hora_texto(h), _clase(regla.clase, mayusculas=True),
                      f"{regla.confianza:.0%}"])
    subtitulo(f"Demanda prevista en los puntos de abordaje (salida {_hora_texto(salida)}, día {args.dia})")
    consola.print(tabla_rich(["Acción", "Estación", "Hora aprox.", "Demanda", "Confianza"], filas))

    def altos(h0: float) -> int:
        return sum(arbol.predecir(ejemplo(atrib[e], _hora_modelo(h), args.dia, args.lluvia)) == "alto"
                   for _, e, h in _abordajes(r, h0))

    actuales = altos(salida)
    consola.print()
    if actuales == 0:
        exito("Ninguna estación de abordaje tendría demanda alta: buen momento para viajar.")
        return
    opciones = [salida + d / 2 for d in range(-4, 5) if HORAS[0] <= salida + d / 2 <= HORAS[-1]]
    mejor = min(opciones, key=lambda h: (altos(h), abs(h - salida)))
    aviso(f"{actuales} punto(s) de abordaje con demanda ALTA: espere filas y buses llenos.")
    if altos(mejor) < actuales:
        consola.print(Text.assemble(("  Sugerencia: ", "tecla"), f"saliendo a las {_hora_texto(mejor)} habría "
                                    f"{altos(mejor)} punto(s) con demanda alta."))


# ---------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m actividad3",
                                description="Actividad 3: árbol de decisión para la demanda de TransMilenio")
    sub = p.add_subparsers(dest="comando")

    def opcion_datos(sp):
        sp.add_argument("--datos", choices=list(RUTAS_DATOS), default="real",
                        help="datos reales de TRANSMILENIO (por defecto) o muestra sintética")

    sp = sub.add_parser("importar", help="descarga y convierte los datos reales de TRANSMILENIO (marzo de 2026)")
    agregar_opciones_importar(sp)

    sp = sub.add_parser("generar", help="genera la muestra sintética en /datos")
    sp.add_argument("--dias", type=int, default=28)
    sp.add_argument("--semilla", type=int, default=SEMILLA)
    sp.set_defaults(func=cmd_generar)

    sp = sub.add_parser("explorar", help="análisis exploratorio del dataset")
    sp.add_argument("--top", type=int, default=10, help="estaciones a listar")
    opcion_datos(sp)
    sp.set_defaults(func=cmd_explorar)

    sp = sub.add_parser("entrenar", help="validación cruzada, entrenamiento, evaluación y reporte")
    opcion_datos(sp)
    sp.add_argument("--criterio", choices=["ganancia", "razon"], default="ganancia",
                    help="ganancia de información (ID3) o razón de ganancia (C4.5)")
    sp.add_argument("--profundidad", type=int, help="fija la profundidad (omite la validación cruzada)")
    sp.add_argument("--max-prof", type=int, default=20, help="profundidad máxima a evaluar")
    sp.add_argument("--min-hoja", type=int, default=20, help="mínimo de ejemplos por hoja")
    sp.add_argument("--pliegues", type=int, default=5)
    sp.set_defaults(func=cmd_entrenar)

    sp = sub.add_parser("reglas", help="muestra las reglas del modelo guardado")
    sp.add_argument("--clase", choices=CLASES)
    sp.add_argument("--top", type=int, default=0, help="solo las N de mayor soporte")
    opcion_datos(sp)
    sp.set_defaults(func=cmd_reglas)

    def opciones_momento(sp):
        sp.add_argument("--hora", required=True, help="hora del día, ej. 7 o 7:30")
        sp.add_argument("--dia", choices=list(FACTOR_TIPO_DIA), default="habil")
        sp.add_argument("--lluvia", action="store_true")
        opcion_datos(sp)

    sp = sub.add_parser("predecir", help="predice la demanda de una estación y explica la regla")
    sp.add_argument("--estacion", required=True)
    opciones_momento(sp)
    sp.set_defaults(func=cmd_predecir)

    sp = sub.add_parser("ruta", help="ruta A* (Actividad 2) + demanda prevista en cada abordaje")
    sp.add_argument("origen")
    sp.add_argument("destino")
    opciones_momento(sp)
    sp.add_argument("-c", "--criterio", choices=["tiempo", "transbordos"], default="tiempo")
    sp.add_argument("--cerrar", nargs="+", metavar="ESTACION")
    sp.set_defaults(func=cmd_ruta)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    utf8_en_consola()
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not args.comando:
        parser.print_help()
        return 0
    try:
        args.func(args)
        return 0
    except (ValueError, ErrorLogico) as e:
        error(str(e), stderr=True)
        return 1
