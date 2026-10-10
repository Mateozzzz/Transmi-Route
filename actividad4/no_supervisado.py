"""
Actividad 4 - Aprendizaje no supervisado sobre la red de TransMilenio.

Problema: sin ninguna etiqueta, descubrir qué TIPOS de estación existen según
su patrón de uso (a qué hora entra y sale la gente, cuánto se usa el fin de
semana, qué tan grande es su demanda). Se usan k-medias y agrupamiento
jerárquico (Ward), se elige k con el codo y la silueta, y los grupos
encontrados se devuelven a la base de conocimiento como hechos lógicos.

Uso:
    python -m actividad4 importar                # descarga y convierte los datos reales (marzo de 2026)
    python -m actividad4 generar                 # crea la muestra sintética en /datos (si no existe)
    python -m actividad4 explorar                # atributos de cada estación
    python -m actividad4 codo [--kmax 8]         # SSE y silueta para k = 2..kmax
    python -m actividad4 agrupar [-k 5]          # agrupa, interpreta, valida y genera el reporte

Por defecto se usan los datos reales; con --datos muestra, la muestra sintética
(sus resultados se guardan aparte, en resultados/muestra/). Con -k fijo, los
resultados de agrupar van a la subcarpeta kN/ (por ejemplo resultados/k5/).
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from aprendizaje import graficos
from aprendizaje.agrupamiento import (altura_de_corte, centroides, cortar, estandarizar, indice_rand_ajustado,
                                      jerarquico, kmedias, silueta, sse, tabla_contingencia)
from aprendizaje.datos import (DESCRIPCION_DATOS, HORAS, NOMBRE_DATOS, RUTA_VALIDACIONES, RUTAS_DATOS, VOCACIONES,
                               atributos_estaciones, cargar_dataset, generar_archivos, vocacion_latente)
from aprendizaje.datos_reales import agregar_opciones_importar
from aprendizaje.salida import escribir, pct, ruta_relativa, tabla_md, utf8_en_consola
from sistema.consola import (Panel, Table, Text, aviso, box, consola, encabezado, error, exito, pares, subtitulo,
                             tabla_rich)
from sistema.logica import ErrorLogico
from sistema.presentacion import ResaltadorLogica
from sistema.red import RedTransporte

DIR_ACTIVIDAD = os.path.dirname(os.path.abspath(__file__))
SEMILLA = 42


def dir_resultados(datos: str) -> str:
    """Datos reales -> resultados/ ; muestra sintética -> resultados/muestra/."""
    base = os.path.join(DIR_ACTIVIDAD, "resultados")
    return base if datos == "real" else os.path.join(base, datos)


def _opcion_datos(datos: str) -> str:
    return "" if datos == "real" else f" --datos {datos}"


# La vocación con la que se generó la muestra sirve de referencia externa: con
# la muestra es la verdad conocida; con los datos reales, solo un supuesto.
_VOCACION = {"muestra": "vocación oculta", "real": "vocación supuesta en la muestra"}
_TITULO_VALIDACION = {"muestra": "Validación externa (solo posible porque los datos son sintéticos)",
                      "real": "Comparación con la vocación supuesta en la muestra (¿se cumplen sus supuestos?)"}

# Ventanas de hora pico. Las salidas se miden una hora más tarde que las
# entradas porque el viaje dura alrededor de una hora.
PICO_AM_ENTRADAS, PICO_PM_ENTRADAS = range(5, 9), range(16, 20)
PICO_AM_SALIDAS, PICO_PM_SALIDAS = range(6, 10), range(17, 21)

ATRIBUTOS = ["log_volumen", "pico_am_entradas", "pico_pm_entradas", "pico_am_salidas", "pico_pm_salidas",
             "ratio_fin_de_semana"]
DESCRIPCION_ATRIBUTOS = {
    "log_volumen": "log10 de las entradas de un día hábil promedio",
    "pico_am_entradas": "fracción de las entradas del día hábil entre 5:00 y 8:59",
    "pico_pm_entradas": "fracción de las entradas del día hábil entre 16:00 y 19:59",
    "pico_am_salidas": "fracción de las salidas del día hábil entre 6:00 y 9:59",
    "pico_pm_salidas": "fracción de las salidas del día hábil entre 17:00 y 20:59",
    "ratio_fin_de_semana": "entradas de un día de fin de semana o festivo / entradas de un día hábil",
}
# Encabezados cortos para que las tablas de la consola quepan en unas 100 columnas
CORTOS = {"log_volumen": "log vol.", "pico_am_entradas": "AM ent.", "pico_pm_entradas": "PM ent.",
          "pico_am_salidas": "AM sal.", "pico_pm_salidas": "PM sal.", "ratio_fin_de_semana": "Fin sem."}
BARRAS = "▁▂▃▄▅▆▇█"


@dataclass
class PerfilEstacion:
    estacion: str
    atributos: Dict[str, float]
    entradas_hora: List[float]     # % de las entradas del día hábil en cada hora de HORAS
    salidas_hora: List[float]
    entradas_dia: float            # entradas de un día hábil promedio

    def vector(self) -> List[float]:
        return [self.atributos[a] for a in ATRIBUTOS]


def perfiles_estaciones(filas: Sequence[Dict[str, object]]) -> List[PerfilEstacion]:
    """Agrega las validaciones (estación × fecha × hora) en un vector por estación."""
    ent: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    sal: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    fin_de_semana: Dict[str, float] = defaultdict(float)
    dias_habiles = {f["fecha"] for f in filas if f["tipo_dia"] == "habil"}
    dias_otros = {f["fecha"] for f in filas if f["tipo_dia"] != "habil"}
    if not dias_habiles or not dias_otros:
        raise ValueError("Se requieren días hábiles y de fin de semana en el dataset.")
    for f in filas:
        e = f["estacion"]
        if f["tipo_dia"] == "habil":
            ent[e][f["hora"]] += f["entradas"]
            sal[e][f["hora"]] += f["salidas"]
        else:
            fin_de_semana[e] += f["entradas"]
    perfiles = []
    for e in sorted(ent):
        total_e, total_s = sum(ent[e].values()), sum(sal[e].values())
        por_dia = total_e / len(dias_habiles)
        perfiles.append(PerfilEstacion(
            e,
            {"log_volumen": math.log10(por_dia),
             "pico_am_entradas": sum(ent[e][h] for h in PICO_AM_ENTRADAS) / total_e,
             "pico_pm_entradas": sum(ent[e][h] for h in PICO_PM_ENTRADAS) / total_e,
             "pico_am_salidas": sum(sal[e][h] for h in PICO_AM_SALIDAS) / total_s,
             "pico_pm_salidas": sum(sal[e][h] for h in PICO_PM_SALIDAS) / total_s,
             "ratio_fin_de_semana": (fin_de_semana[e] / len(dias_otros)) / por_dia},
            [100 * ent[e][h] / total_e for h in HORAS],
            [100 * sal[e][h] / total_s for h in HORAS],
            por_dia))
    return perfiles


def _cargar(datos: str) -> List[PerfilEstacion]:
    return perfiles_estaciones(cargar_dataset(RUTAS_DATOS[datos]))


def chispa(valores: Sequence[float]) -> str:
    """Mini gráfico de texto (sparkline)."""
    lo, hi = min(valores), max(valores)
    return "".join(BARRAS[int((v - lo) / (hi - lo) * (len(BARRAS) - 1)) if hi > lo else 0] for v in valores)


def color_grupo(g: int) -> str:
    """El mismo color que tiene el grupo en los gráficos SVG."""
    return graficos.SERIES[g % len(graficos.SERIES)][1]


# ---------------------------------------------------------------------------
# Interpretación de los grupos
# ---------------------------------------------------------------------------

def nombrar_grupos(centros: Sequence[Sequence[float]], centros_z: Sequence[Sequence[float]]) -> List[Tuple[str, str]]:
    """(nombre legible, identificador) de cada grupo a partir de su centroide.

    índice residencial = (entradas AM - entradas PM) + (salidas PM - salidas AM):
        > 0  la gente SALE de la estación en la mañana y VUELVE en la tarde (vive cerca)
        < 0  la gente LLEGA en la mañana y se va en la tarde (trabaja cerca)
    Un uso en fin de semana muy por encima del resto (z >= 1) indica comercio,
    eventos o estudio: el grupo se llama "Ocio / fin de semana".
    """
    i = {a: j for j, a in enumerate(ATRIBUTOS)}
    nombres = []
    for c, z in zip(centros, centros_z):
        indice = (c[i["pico_am_entradas"]] - c[i["pico_pm_entradas"]]
                  + c[i["pico_pm_salidas"]] - c[i["pico_am_salidas"]])
        if z[i["ratio_fin_de_semana"]] >= 1.0:
            nombre, ident = "Ocio / fin de semana", "ocio_fin_de_semana"
        elif indice >= 0.25:
            nombre, ident = "Residencial", "residencial"
        elif indice <= -0.25:
            nombre, ident = "Empleo / oficinas", "empleo"
        else:
            nombre, ident = "Mixta", "mixta"
        if z[i["log_volumen"]] >= 1.5:
            nombre, ident = nombre + " - alta demanda", ident + "_alta_demanda"
        nombres.append((nombre, ident))
    # Nombres repetidos -> se numeran (se compara con la lista original: al
    # renombrar el primero, el segundo dejaría de parecer repetido)
    originales = list(nombres)
    for n, (nombre, ident) in enumerate(originales):
        repetidos = [m for m, (_, otro) in enumerate(originales) if otro == ident]
        if len(repetidos) > 1:
            j = repetidos.index(n) + 1
            nombres[n] = (f"{nombre} {j}", f"{ident}_{j}")
    return nombres


def hechos_perfiles(estaciones: Sequence[str], etiquetas: Sequence[int], identificadores: Sequence[str],
                    datos: str = "real") -> str:
    """Base de hechos perfil_estacion/2, en la sintaxis de la Actividad 2."""
    return "\n".join(
        [f"% Perfiles de uso de las estaciones descubiertos con k-medias (Actividad 4, {NOMBRE_DATOS[datos]}).",
         f"% Generado con: python -m actividad4 agrupar -k {len(identificadores)}{_opcion_datos(datos)}",
         "% Se puede cargar junto con conocimiento/hechos.kb y conocimiento/reglas.kb.", ""]
        + [f'perfil_estacion("{e}", "{identificadores[g]}").' for e, g in zip(estaciones, etiquetas)]) + "\n"


def ordenar_por_tamano(etiquetas: Sequence[int]) -> List[int]:
    """Renumera los grupos de mayor a menor tamaño (empate: primera aparición)."""
    tam = defaultdict(int)
    for e in etiquetas:
        tam[e] += 1
    orden = sorted(tam, key=lambda g: (-tam[g], etiquetas.index(g)))
    nuevo = {g: i for i, g in enumerate(orden)}
    return [nuevo[e] for e in etiquetas]


def alinear(referencia: Sequence[int], etiquetas: Sequence[int]) -> List[int]:
    """Renumera 'etiquetas' para que coincidan lo más posible con 'referencia'
    (emparejamiento voraz por la tabla de contingencia). Así un mismo grupo
    conserva su color en todos los gráficos."""
    cont = tabla_contingencia(etiquetas, referencia)
    mapa: Dict[int, int] = {}
    usados = set()
    for (g, r), _ in sorted(cont.items(), key=lambda kv: (-kv[1], kv[0])):
        if g not in mapa and r not in usados:
            mapa[g] = r
            usados.add(r)
    libres = iter(sorted(set(range(max(etiquetas) + max(referencia) + 2)) - usados))
    for g in sorted(set(etiquetas)):
        if g not in mapa:
            mapa[g] = next(libres)
    return [mapa[e] for e in etiquetas]


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_generar(args) -> None:
    if os.path.exists(RUTA_VALIDACIONES) and not args.forzar:
        aviso(f"Ya existe {ruta_relativa(RUTA_VALIDACIONES, os.getcwd())} (use --forzar para regenerarlo).")
        return
    filas, estaciones = generar_archivos(args.dias, args.semilla)
    exito(f"Dataset generado: {filas} filas, {estaciones} estaciones.")


def cmd_explorar(args) -> None:
    perfiles = _cargar(args.datos)
    encabezado(f"{len(perfiles)} estaciones descritas por {len(ATRIBUTOS)} atributos",
               f"Días hábiles, {NOMBRE_DATOS[args.datos]}")
    consola.print(pares([(CORTOS[a], Text.assemble((a, "dato"), f": {DESCRIPCION_ATRIBUTOS[a]}")) for a in ATRIBUTOS]))
    consola.print()
    consola.print(tabla_rich(["Estación", "Entradas/día"] + [CORTOS[a] for a in ATRIBUTOS[1:]] + ["Perfil 4h-22h"],
                             [[Text(p.estacion, style="estacion"), f"{p.entradas_dia:,.0f}".replace(",", ".")]
                              + [f"{p.atributos[a]:.3f}" for a in ATRIBUTOS[1:]]
                              + [Text(chispa(p.entradas_hora), style="chispa")] for p in perfiles], compacta=True))
    subtitulo("Resumen de los atributos")
    consola.print(tabla_rich(["Atributo", "Mín", "Media", "Máx", "Desv."],
                             [[a, *(f"{v:.3f}" for v in (min(c), statistics.mean(c), max(c), statistics.pstdev(c)))]
                              for a, c in ((a, [p.atributos[a] for p in perfiles]) for a in ATRIBUTOS)]))


@dataclass
class Barrido:
    ks: List[int]
    sse: List[float]
    silueta_kmedias: List[float]
    silueta_ward: List[float]
    k_sugerido: int


def barrido_k(Z: Sequence[Sequence[float]], kmax: int, fusiones) -> Barrido:
    ks = list(range(2, kmax + 1))
    sse, sil_k, sil_w = [], [], []
    for k in ks:
        r = kmedias(Z, k, SEMILLA)
        sse.append(r.sse)
        sil_k.append(silueta(Z, r.etiquetas))
        sil_w.append(silueta(Z, cortar(fusiones, len(Z), k)))
    mejor = ks[max(range(len(ks)), key=lambda i: sil_k[i])]
    return Barrido(ks, sse, sil_k, sil_w, mejor)


def _graficos_barrido(b: Barrido, k: int, directorio: str) -> None:
    graficos.guardar(graficos.lineas(
        b.ks, {"SSE": b.sse}, "Método del codo (k-medias)",
        "Suma de errores cuadráticos dentro de los grupos, atributos estandarizados",
        "número de grupos k", "SSE", marcar_x=k, texto_marca=f"k = {k}", y_desde_cero=True),
        os.path.join(directorio, "codo.svg"))
    graficos.guardar(graficos.lineas(
        b.ks, {"k-medias": b.silueta_kmedias, "Jerárquico (Ward)": b.silueta_ward},
        "Coeficiente de silueta según k", "Más alto = grupos más compactos y mejor separados (máximo 1)",
        "número de grupos k", "silueta promedio", marcar_x=k, texto_marca=f"k = {k}"),
        os.path.join(directorio, "silueta.svg"))


def cmd_codo(args) -> None:
    perfiles = _cargar(args.datos)
    directorio = dir_resultados(args.datos)
    Z, _, _ = estandarizar([p.vector() for p in perfiles])
    with consola.status("Ejecutando k-medias y Ward para cada k ..."):
        b = barrido_k(Z, args.kmax, jerarquico(Z, "ward"))
    encabezado(f"Número de grupos: codo y silueta para k = 2 a {args.kmax}", NOMBRE_DATOS[args.datos])
    consola.print(tabla_rich(["k", "SSE (k-medias)", "Silueta k-medias", "Silueta Ward"],
                             [[k, f"{s:.1f}", f"{a:.3f}", f"{w:.3f}"]
                              for k, s, a, w in zip(b.ks, b.sse, b.silueta_kmedias, b.silueta_ward)],
                             estilos_fila=["resumen" if k == b.k_sugerido else None for k in b.ks]))
    consola.print(Text.assemble(("k con mayor silueta (k-medias): ", "nota"), (str(b.k_sugerido), "resumen")))
    os.makedirs(directorio, exist_ok=True)
    _graficos_barrido(b, b.k_sugerido, directorio)
    consola.print(Text(f"Gráficos: {ruta_relativa(directorio, os.getcwd())}/codo.svg, silueta.svg", style="nota"))


def cmd_agrupar(args) -> None:
    t0 = time.perf_counter()
    red = RedTransporte()
    perfiles = _cargar(args.datos)
    # Con -k fijo, los resultados van a resultados/kN/ y no sobrescriben el análisis por defecto
    directorio = dir_resultados(args.datos) if not args.k else os.path.join(dir_resultados(args.datos), f"k{args.k}")
    estaciones = [p.estacion for p in perfiles]
    X = [p.vector() for p in perfiles]
    Z, medias, desv = estandarizar(X)
    n = len(Z)
    with consola.status("Agrupando las estaciones con k-medias y Ward ..."):
        fusiones = jerarquico(Z, "ward")
        barrido = barrido_k(Z, args.kmax, fusiones)
        k = args.k or barrido.k_sugerido
        if not 2 <= k <= n:
            raise ValueError(f"k debe estar entre 2 y {n}")

        res = kmedias(Z, k, SEMILLA)
        etiq_k = ordenar_por_tamano(res.etiquetas)
        etiq_w = alinear(etiq_k, cortar(fusiones, n, k))
        centros = centroides(X, etiq_k)
        nombres = nombrar_grupos(centros, centroides(Z, etiq_k))
        sil_k, sil_w = silueta(Z, etiq_k), silueta(Z, etiq_w)
        ari_kw = indice_rand_ajustado(etiq_k, etiq_w)
        atrib = atributos_estaciones(red)
        vocacion = [vocacion_latente(e, atrib[e]) for e in estaciones]
        ari_voc_k, ari_voc_w = indice_rand_ajustado(etiq_k, vocacion), indice_rand_ajustado(etiq_w, vocacion)

    encabezado(f"Agrupamiento de {n} estaciones en k = {k} grupos",
               f"k {'elegido por la silueta' if not args.k else 'fijado por el usuario'}; "
               f"cada grupo tiene el color que usa en los gráficos.")
    for g in range(k):
        miembros = [p for p, e in zip(perfiles, etiq_k) if e == g]
        perfil_medio = [statistics.mean(p.entradas_hora[i] for p in miembros) for i in range(len(HORAS))]
        centroide = Table(box=None, header_style="nota", pad_edge=False)
        for a in ATRIBUTOS:
            centroide.add_column(CORTOS[a], justify="right")
        centroide.add_row(*(f"{v:.3f}" for v in centros[g]))
        consola.print(Panel(
            pares([("Entradas por hora", Text(f"{chispa(perfil_medio)}  (4h-22h)", style=color_grupo(g))),
                   ("Entradas por día", f"≈ {10 ** centros[g][0]:,.0f}".replace(",", ".")),
                   ("Centroide", centroide),
                   ("Estaciones", ", ".join(p.estacion for p in miembros))]),
            title=Text(f"Grupo {g + 1}: {nombres[g][0]} ({len(miembros)} estaciones)", style=f"bold {color_grupo(g)}"),
            title_align="left", border_style=color_grupo(g), box=box.ROUNDED, padding=(0, 1)))
    subtitulo("Comparación de los dos métodos")
    consola.print(tabla_rich(["Medida", "k-medias", "Jerárquico (Ward)"],
                             [["Silueta promedio", f"{sil_k:.3f}", f"{sil_w:.3f}"],
                              ["SSE", f"{sse(Z, etiq_k):.1f}", f"{sse(Z, etiq_w):.1f}"],
                              [f"ARI vs. {_VOCACION[args.datos]}", f"{ari_voc_k:.3f}", f"{ari_voc_w:.3f}"]]))
    consola.print(Text.assemble(("Concordancia k-medias vs. Ward (índice de Rand ajustado): ", "nota"),
                                (f"{ari_kw:.3f}", "dato")))
    distintas = [e for e, a, b in zip(estaciones, etiq_k, etiq_w) if a != b]
    if distintas:
        consola.print(Text.assemble(("Estaciones asignadas distinto por los dos métodos: ", "nota"),
                                    ", ".join(distintas)))

    subtitulo(_TITULO_VALIDACION[args.datos])
    cont = tabla_contingencia(etiq_k, vocacion)
    filas_cont = []
    for g in range(k):
        conteos = [cont.get((g, v), 0) for v in VOCACIONES]
        filas_cont.append([Text(nombres[g][0], style=f"bold {color_grupo(g)}")]
                          + [Text(str(c), style="dato" if c and c == max(conteos) else "nota" if not c else "")
                             for c in conteos])
    consola.print(tabla_rich(["Grupo \\ vocación"] + VOCACIONES, filas_cont))

    # --- archivos ---
    os.makedirs(directorio, exist_ok=True)
    _graficos_barrido(barrido, k, directorio)
    nombres_cortos = [nm for nm, _ in nombres]
    for sentido, attr in (("entradas", "entradas_hora"), ("salidas", "salidas_hora")):
        series = {nombres_cortos[g]: [statistics.mean(getattr(p, attr)[i] for p, e in zip(perfiles, etiq_k) if e == g)
                                      for i in range(len(HORAS))] for g in range(k)}
        graficos.guardar(graficos.lineas(
            HORAS, series, f"Perfil horario de {sentido} por grupo",
            f"Porcentaje de las {sentido} de un día hábil que ocurre en cada hora (promedio del grupo)",
            "hora del día", f"% de las {sentido} diarias", y_desde_cero=True,
            marcas_x=list(range(4, 23, 2)), formato_y=lambda v: f"{v:g} %"),
            os.path.join(directorio, f"perfiles_{sentido}.svg"))
    segmentos = sorted({tuple(sorted((a, b))) for a, b, _ in red.kb.buscar("siguiente", None, None, None)})
    # Coordenadas de toda la red: las estaciones sin datos también se dibujan (en gris)
    graficos.guardar(graficos.mapas_por_grupo(
        {e: (a["latitud"], a["longitud"]) for e, a in atrib.items()},
        dict(zip(estaciones, etiq_k)), nombres_cortos, segmentos,
        f"Grupos de estaciones encontrados por k-medias (k = {k})",
        "Cada panel resalta un grupo sobre la red troncal; el resto de estaciones en gris"),
        os.path.join(directorio, "mapa_clusters.svg"))
    nombres_w = nombrar_grupos(centroides(X, etiq_w), centroides(Z, etiq_w))
    graficos.guardar(graficos.dendrograma(
        fusiones, estaciones, etiq_w, [nm for nm, _ in nombres_w], "Dendrograma - agrupamiento jerárquico (enlace de Ward)",
        f"Línea de corte en {k} grupos; el color indica el grupo de cada estación",
        altura_corte=altura_de_corte(fusiones, n, k)), os.path.join(directorio, "dendrograma.svg"))

    ruta_kb = os.path.join(directorio, "perfiles.kb")
    escribir(ruta_kb, hechos_perfiles(estaciones, etiq_k, [ident for _, ident in nombres], args.datos))
    escribir(os.path.join(directorio, "asignacion.csv"), "\n".join(
        ["estacion,grupo_kmedias,grupo_ward," + ",".join(ATRIBUTOS)]
        + [f'"{p.estacion}",{nombres[a][1]},{nombres_w[b][1]},' + ",".join(f"{p.atributos[x]:.4f}" for x in ATRIBUTOS)
           for p, a, b in zip(perfiles, etiq_k, etiq_w)]) + "\n")

    # Lo aprendido vuelve a la base de conocimiento de la Actividad 2
    red.kb.cargar_archivo(ruta_kb)
    integracion = red.kb.consultar("perfil_estacion(E, P), estacion_de_integracion(E)")
    subtitulo("Consulta lógica sobre la base de conocimiento + perfiles aprendidos")
    consola.print(ResaltadorLogica()("perfil_estacion(E, P), estacion_de_integracion(E)"))
    consola.print(tabla_rich(["E", "P"], [[Text(f["E"], style="estacion"), f["P"]] for f in integracion]))

    escribir(os.path.join(directorio, "reporte.md"), _reporte(
        args, k, barrido, perfiles, etiq_k, etiq_w, nombres, centros, sil_k, sil_w, ari_kw,
        ari_voc_k, ari_voc_w, vocacion, distintas, integracion, medias, desv))
    consola.print()
    exito(f"Reporte, gráficos, perfiles.kb y asignacion.csv en {ruta_relativa(directorio, os.getcwd())}/ "
          f"({time.perf_counter() - t0:.1f} s)")


def _reporte(args, k, barrido, perfiles, etiq_k, etiq_w, nombres, centros, sil_k, sil_w, ari_kw,
             ari_voc_k, ari_voc_w, vocacion, distintas, integracion, medias, desv) -> str:
    cont = tabla_contingencia(etiq_k, vocacion)
    md = ["# Resultados - Actividad 4: agrupamiento de estaciones de TransMilenio", "",
          f"Generado el {date.today():%Y-%m-%d} con `python -m actividad4 agrupar"
          + (f" -k {args.k}" if args.k else "") + f"{_opcion_datos(args.datos)}`.", "",
          "## Datos y atributos", "",
          f"Fuente: {DESCRIPCION_DATOS[args.datos]}.", "",
          f"{len(perfiles)} estaciones. Cada una se describe con {len(ATRIBUTOS)} atributos calculados a partir "
          "de sus entradas y salidas, y luego estandarizados (puntuación z):", "",
          tabla_md(["Atributo", "Descripción", "Media", "Desv."],
                   [[f"`{a}`", DESCRIPCION_ATRIBUTOS[a], f"{m:.3f}", f"{d:.3f}"]
                    for a, m, d in zip(ATRIBUTOS, medias, desv)]), "",
          "## Elección del número de grupos", "",
          "![Codo](codo.svg)", "", "![Silueta](silueta.svg)", "",
          tabla_md(["k", "SSE (k-medias)", "Silueta k-medias", "Silueta Ward"],
                   [[kk, f"{s:.1f}", f"{a:.3f}", f"{w:.3f}"] for kk, s, a, w in
                    zip(barrido.ks, barrido.sse, barrido.silueta_kmedias, barrido.silueta_ward)]), "",
          f"La silueta de k-medias es máxima en k = {barrido.k_sugerido}. "
          + (f"**Se usa k = {k}.**" if k == barrido.k_sugerido else f"**Se usa k = {k} (fijado por el usuario).**"),
          "", "## Grupos encontrados (k-medias)", ""]
    filas = []
    for g in range(k):
        miembros = [p.estacion for p, e in zip(perfiles, etiq_k) if e == g]
        filas.append([f"{g + 1}. {nombres[g][0]}", len(miembros), f"{10 ** centros[g][0]:,.0f}".replace(",", ".")]
                     + [f"{v:.2f}" for v in centros[g][1:]])
    md += [tabla_md(["Grupo", "Estaciones", "Entradas/día"] + [f"`{a}`" for a in ATRIBUTOS[1:]], filas), ""]
    for g in range(k):
        miembros = [p.estacion for p, e in zip(perfiles, etiq_k) if e == g]
        md += [f"- **{nombres[g][0]}** ({len(miembros)}): {', '.join(miembros)}."]
    md += ["", "![Mapa de los grupos](mapa_clusters.svg)", "",
           "![Perfil horario de entradas](perfiles_entradas.svg)", "",
           "![Perfil horario de salidas](perfiles_salidas.svg)", "",
           "## Comparación con el agrupamiento jerárquico (Ward)", "",
           "![Dendrograma](dendrograma.svg)", "",
           tabla_md(["Medida", "k-medias", "Jerárquico (Ward)"],
                    [["Silueta promedio", f"{sil_k:.3f}", f"{sil_w:.3f}"],
                     [f"Índice de Rand ajustado vs. {_VOCACION[args.datos]}", f"{ari_voc_k:.3f}", f"{ari_voc_w:.3f}"]]),
           "",
           f"Concordancia entre los dos métodos (índice de Rand ajustado): **{ari_kw:.3f}**. "
           + (f"Estaciones asignadas distinto: {', '.join(distintas)}." if distintas
              else "Los dos métodos producen exactamente la misma partición."), ""]
    if args.datos == "muestra":
        md += ["## Validación externa", "",
               "Como los datos son una muestra sintética, se conoce la vocación con la que se generó cada estación "
               "(no se usó para agrupar). La tabla compara los grupos con esa vocación oculta:", ""]
    else:
        md += ["## ¿Se cumplen los supuestos de la muestra?", "",
               "La muestra sintética se generó suponiendo una vocación para cada estación: empleo o educativa / "
               "ocio según una lista de atractores (Calle 72, Calle 100, CAN, U. Nacional, Campín, Corferias, ...), "
               "residencial si es portal o está a más de 7,5 km del centro, y mixta en otro caso. Esa vocación no "
               "se usó para agrupar. La tabla la compara con los grupos encontrados en los datos reales:", ""]
    md += [tabla_md(["Grupo \\ vocación"] + VOCACIONES,
                    [[nombres[g][0]] + [cont.get((g, v), 0) for v in VOCACIONES] for g in range(k)]), "",
           "## De vuelta a la base de conocimiento", "",
           "Los grupos se exportan como hechos lógicos en [perfiles.kb](perfiles.kb) "
           "(`perfil_estacion(Estacion, Perfil).`) y se consultan junto con las reglas de la Actividad 2. "
           "Por ejemplo, el perfil de las estaciones de integración que infiere la base de conocimiento:", "",
           "```text", "perfil_estacion(E, P), estacion_de_integracion(E)",
           *[f"  {f['E']}: {f['P']}" for f in integracion], "```", "",
           "La asignación completa de cada estación está en [asignacion.csv](asignacion.csv).", ""]
    return "\n".join(md)


# ---------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m actividad4",
                                description="Actividad 4: agrupamiento de estaciones de TransMilenio")
    sub = p.add_subparsers(dest="comando")

    def opcion_datos(sp):
        sp.add_argument("--datos", choices=list(RUTAS_DATOS), default="real",
                        help="datos reales de TRANSMILENIO (por defecto) o muestra sintética")

    sp = sub.add_parser("importar", help="descarga y convierte los datos reales de TRANSMILENIO (marzo de 2026)")
    agregar_opciones_importar(sp)

    sp = sub.add_parser("generar", help="genera la muestra sintética en /datos (si no existe)")
    sp.add_argument("--dias", type=int, default=28)
    sp.add_argument("--semilla", type=int, default=SEMILLA)
    sp.add_argument("--forzar", action="store_true", help="regenera aunque ya exista")
    sp.set_defaults(func=cmd_generar)

    sp = sub.add_parser("explorar", help="atributos de cada estación")
    opcion_datos(sp)
    sp.set_defaults(func=cmd_explorar)

    sp = sub.add_parser("codo", help="SSE y silueta para distintos k")
    sp.add_argument("--kmax", type=int, default=8)
    opcion_datos(sp)
    sp.set_defaults(func=cmd_codo)

    sp = sub.add_parser("agrupar", help="k-medias + jerárquico, interpretación, validación y reporte")
    sp.add_argument("-k", type=int,
                    help="número de grupos (por defecto, el de mayor silueta); los resultados van a resultados/kN/")
    sp.add_argument("--kmax", type=int, default=8)
    opcion_datos(sp)
    sp.set_defaults(func=cmd_agrupar)
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
