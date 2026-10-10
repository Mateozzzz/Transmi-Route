"""
Datos reales de TRANSMILENIO: entradas y salidas por estación y hora.

Fuentes
-------
TRANSMILENIO S.A. publica en su repositorio de datos abiertos (validaciones_tmsa)
reportes mensuales agregados cada 15 minutos por estación y acceso, con una
columna por día del mes:

    entradas: "TM Resumen de Validaciones Troncales ... Intervalo 15 Mint.xlsx"
    salidas:  "Resumen_Salidas_Cada_15_minutos_<Mes>_<Año>.xlsx"

La lluvia horaria se toma de la API histórica de Open-Meteo (CC BY 4.0) en el
centro de Bogotá.

Conversión
----------
1. Lee los XLSX con la librería estándar (zipfile + xml.etree), sin pandas ni
   openpyxl. Solo cuenta las filas de detalle (estación "(código) nombre" con
   un intervalo válido): la hoja trae además una fila de total general que
   duplicaría las cifras.
2. Suma los accesos de cada estación y los cuatro intervalos de 15 minutos de
   cada hora.
3. Enlaza cada estación de la base de conocimiento con su código en el sistema
   de recaudo (CODIGOS_ESTACION); el código no cambia con los nombres
   comerciales ("Portal Norte - Unicervantes", "Toberin - Foundever", ...).
4. Escribe datos/afluencia_transmilenio_real.csv con las mismas columnas que la
   muestra sintética, así las Actividades 3 y 4 trabajan con cualquiera de los dos.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

# aviso como advertir: aquí 'aviso' es el parámetro que recibe los mensajes de progreso
from sistema.consola import Text, aviso as advertir, consola, encabezado, pares, subtitulo, tabla_rich
from sistema.red import RedTransporte
from .datos import CENTRO, COLUMNAS_VALIDACIONES, DIAS_SEMANA, DIR_DATOS, HORAS, RUTA_REAL, guardar_csv, tipo_de_dia
from .salida import pct, ruta_relativa

REPOSITORIO = "https://storage.googleapis.com/validaciones_tmsa"
URL_ENTRADAS = (REPOSITORIO + "/ValidacionTroncal/2026/03%20TM%20Resumen%20de%20Validaciones%20Troncales"
                "%20al%2031%20de%20Marzo%20del%202026%20Intervalo%2015%20Mint.xlsx")
URL_SALIDAS = REPOSITORIO + "/Salidas/2026/Resumen_Salidas_Cada_15_minutos_Marzo_2026.xlsx"
URL_LLUVIA = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
              "&start_date={desde}&end_date={hasta}&hourly=precipitation&timezone=America%2FBogota")

# Las mismas 4 semanas de la muestra sintética. El 30 y el 31 de marzo (lunes y
# martes de Semana Santa) tienen cerca de 20 % menos validaciones y se dejan fuera.
INICIO_REAL, FIN_REAL = date(2026, 3, 2), date(2026, 3, 29)
UMBRAL_LLUVIA_MM = 0.2           # precipitación en la hora para considerar que llovió
DIR_CRUDOS = os.path.join(DIR_DATOS, "crudos")

# Código de cada estación de la base de conocimiento en el sistema de recaudo
# (marzo de 2026). Por las obras de la primera línea del metro, varias estaciones
# de la Caracas operan como "Temporal ..." y otras están cerradas (sin datos: ()).
# Algunas estaciones tienen dos códigos y se suman.
CODIGOS_ESTACION: Dict[str, Tuple[str, ...]] = {
    # B - Autopista Norte
    "Portal Norte": ("02000",), "Toberín": ("02101",), "Calle 161": ("02102",), "Mazurén": ("02103",),
    "Calle 146": ("02104",), "Calle 142": ("02105",), "Alcalá": ("02200",), "Prado": ("02201",),
    "Calle 127": ("02202",), "Pepe Sierra": ("02204",), "Calle 106": ("02205",), "Calle 100": ("02300",),
    "Virrey": ("02302",), "Calle 85": ("02303",), "Héroes": ("02304",),
    # A - Caracas
    "Calle 76": ("09123",), "Flores": ("09121",), "Calle 45": ("09117",), "Calle 26": ("09114",),
    "Av. Jiménez": ("09110", "09128"),                 # Avenida Jiménez + Temporal Avenida Jiménez
    "Calle 57": ("09125",), "Marly": ("09126",), "Av. 39": ("09130",), "Calle 34": ("09124",),
    "Calle 22": ("09129",),                            # temporales
    "Calle 72": (), "Calle 63": (), "Calle 19": (), "Tercer Milenio": (),   # cerradas
    # D - Calle 80
    "Portal 80": ("04000",), "Quirigua": ("04001",), "Carrera 90": ("04002",), "Av. Ciudad de Cali": ("04003",),
    "Granja - Carrera 77": ("04004", "04100"),         # La Granja + Carrera 77
    "Minuto de Dios": ("04101",), "Av. Boyacá": ("04102",), "Ferias": ("04103",), "Av. 68": ("04104",),
    "Carrera 53": ("04105",), "Carrera 47": ("04106",), "Escuela Militar": ("04107",), "Polo": ("04108",),
    # E - NQS
    "La Castellana": ("07101",), "NQS Calle 75": ("07102",), "Av. Chile": ("07103",), "7 de Agosto": ("07104",),
    "Movistar Arena": ("07105",), "Campín": ("07106",), "U. Nacional": ("07107",), "Av. El Dorado": ("07108",),
    "CAD": ("07109",), "Paloquemao": ("07110",),
    "Ricaurte": ("07111", "12003"),                    # NQS - Ricaurte (E) + Ricaurte (F)
    # F - Américas y Calle 13
    "Portal Américas": ("05000",), "Biblioteca Tintal": ("05002",), "Transversal 86": ("05005",),
    "Banderas": ("05100",), "Mandalay": ("05101",), "Américas - Av. Boyacá": ("05102",), "Marsella": ("05103",),
    "Pradera": ("05105",), "Distrito Grafiti": ("05107",),   # antes "Américas - Carrera 53 A"
    "Puente Aranda": ("12000",), "Carrera 43": ("12001",), "CDS - Carrera 32": ("12002",),
    "San Façón - Carrera 22": ("12004",), "Zona Industrial": ("12007",), "De La Sabana": ("14001",),
    "Patio Bonito": (),                                # sin datos en el sistema de recaudo
    # J - Eje Ambiental
    "Museo del Oro": ("14004",), "Las Aguas": ("14005",),
    # K - Calle 26
    "Portal El Dorado": ("06000",), "Modelia": ("06001",), "Normandía": ("06002",), "Av. Rojas": ("06100",),
    "El Tiempo - Maloka": ("06101",), "Salitre - El Greco": ("06102",), "CAN": ("06103",),
    "Gobernación": ("06104",), "Quinta Paredes": ("06105",), "Corferias": ("06106",),
    "Ciudad Universitaria": ("06107",), "Concejo de Bogotá": ("06108",), "Centro Memoria": ("06109",),
    "Universidades": ("06111",),
}

Conteos = Dict[Tuple[str, date, int], int]     # (código, fecha, hora) -> validaciones


# ---------------------------------------------------------------------------
# Lectura de los XLSX (Office Open XML) con la librería estándar
# ---------------------------------------------------------------------------

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _texto(nodo: ET.Element) -> str:
    return "".join(t.text or "" for t in nodo.iter(_NS + "t"))


def _columna(ref: str) -> int:
    """'AJ7' -> 35 (índice desde 0)."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _valor(celda: ET.Element, compartidas: Sequence[str]) -> str:
    tipo = celda.get("t")
    if tipo == "inlineStr":
        return _texto(celda)
    v = celda.find(_NS + "v")
    if v is None or v.text is None:
        return ""
    return compartidas[int(v.text)] if tipo == "s" else v.text


def _es_encabezado(fila: Dict[int, str]) -> bool:
    textos = [v.strip().lower() for v in fila.values()]
    return any(t.startswith("estaci") for t in textos) and any(t.startswith("interv") for t in textos)


def filas_xlsx(ruta: str) -> Iterator[Dict[int, str]]:
    """Filas (columna -> texto) de la primera hoja que tenga un encabezado con
    'Estación' e 'Intervalo', empezando por ese encabezado. El XML se lee en
    flujo porque cada hoja tiene unas 50.000 filas."""
    if not zipfile.is_zipfile(ruta):
        raise ValueError(f"{ruta} no es un archivo XLSX válido.")
    # Cada miembro abierto del ZIP se cierra con 'with': en Windows, uno abierto
    # deja el archivo bloqueado aunque el ZipFile ya esté cerrado.
    with zipfile.ZipFile(ruta) as z:
        compartidas: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                for _, el in ET.iterparse(f):
                    if el.tag == _NS + "si":
                        compartidas.append(_texto(el))
                        el.clear()
        hojas = sorted((n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                       key=lambda n: int(re.search(r"\d+", n).group()))
        for hoja in hojas:
            encontrado = False
            with z.open(hoja) as f:
                for _, el in ET.iterparse(f):
                    if el.tag != _NS + "row":
                        continue
                    fila, siguiente = {}, 0
                    for c in el.findall(_NS + "c"):
                        col = _columna(c.get("r")) if c.get("r") else siguiente
                        fila[col], siguiente = _valor(c, compartidas), col + 1
                    el.clear()
                    if encontrado or _es_encabezado(fila):
                        encontrado = True
                        yield fila
            if encontrado:
                return
    raise ValueError(f"{ruta}: ninguna hoja tiene un encabezado con columnas 'Estación' e 'Intervalo'.")


def _fecha_de_columna(texto: str) -> Optional[date]:
    """'46083' (número de serie de Excel) o '_2026_03_02' -> fecha."""
    t = texto.strip()
    m = re.fullmatch(r"_?(\d{4})_(\d{2})_(\d{2})", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if re.fullmatch(r"\d{5}(\.0+)?", t):
        return date(1899, 12, 30) + timedelta(days=int(float(t)))
    return None


def _hora_de_intervalo(texto: str) -> Optional[int]:
    """'06:15:00' o 0.2604... (fracción del día) -> 6."""
    t = texto.strip()
    try:
        hora = int(t.split(":")[0]) if ":" in t else int(float(t) * 24 + 1e-6)
    except ValueError:
        return None
    return hora if 0 <= hora <= 23 else None


@dataclass
class ReporteIntervalos:
    conteos: Conteos               # suma de accesos e intervalos de 15 min por hora
    nombres: Dict[str, str]        # código -> nombre en el reporte
    total_por_dia: Dict[date, int]  # todas las filas de detalle (control contra el reporte oficial)


def leer_intervalos(ruta: str) -> ReporteIntervalos:
    filas = filas_xlsx(ruta)
    encabezado = next(filas)
    col_estacion = min(c for c, t in encabezado.items() if t.strip().lower().startswith("estaci"))
    col_intervalo = min(c for c, t in encabezado.items() if t.strip().lower().startswith("interv"))
    fechas = {c: f for c, f in ((c, _fecha_de_columna(t)) for c, t in encabezado.items()) if f}
    if not fechas:
        raise ValueError(f"{ruta}: el encabezado no tiene columnas de fecha.")
    conteos: Conteos = defaultdict(int)
    nombres: Dict[str, str] = {}
    total: Dict[date, int] = defaultdict(int)
    for fila in filas:
        estacion = fila.get(col_estacion, "")
        m = re.match(r"\s*\((\d+)\)", estacion)
        hora = _hora_de_intervalo(fila.get(col_intervalo, ""))
        if not m or hora is None:
            continue                   # filas vacías y fila de total general
        codigo = m.group(1)
        nombres.setdefault(codigo, estacion[m.end():].strip())
        for c, f in fechas.items():
            try:
                n = int(round(float(fila.get(c, ""))))
            except ValueError:
                continue               # 'X' (el día no existe en el mes) o celda vacía
            conteos[(codigo, f, hora)] += n
            total[f] += n
    return ReporteIntervalos(dict(conteos), nombres, dict(total))


# ---------------------------------------------------------------------------
# Descargas y lluvia
# ---------------------------------------------------------------------------

def obtener(fuente: str, nombre: Optional[str] = None, aviso: Callable[[str], None] = print) -> str:
    """Ruta local de 'fuente' (archivo o URL). Las URL se descargan una sola vez a datos/crudos/."""
    if os.path.exists(fuente):
        return fuente
    if not fuente.startswith(("http://", "https://")):
        raise ValueError(f"No existe el archivo {fuente}")
    nombre = nombre or urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(fuente).path))
    destino = os.path.join(DIR_CRUDOS, nombre)
    if not os.path.exists(destino):
        os.makedirs(DIR_CRUDOS, exist_ok=True)
        aviso(f"Descargando {nombre} ...")
        pedido = urllib.request.Request(fuente, headers={"User-Agent": "transmi-ruta-ia"})
        try:
            with urllib.request.urlopen(pedido, timeout=300) as r, open(destino + ".parcial", "wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as e:
            if os.path.exists(destino + ".parcial"):
                os.remove(destino + ".parcial")
            raise ValueError(f"No se pudo descargar {fuente} ({e}). Descárguelo a mano y pase la ruta del "
                             "archivo con --entradas / --salidas.") from None
        os.replace(destino + ".parcial", destino)
    return destino


def lluvia_por_hora(desde: date, hasta: date, lat: float, lon: float,
                    aviso: Callable[[str], None] = print) -> Dict[Tuple[date, int], bool]:
    """(fecha, hora) -> si llovió al menos UMBRAL_LLUVIA_MM (Open-Meteo, hora de Bogotá)."""
    ruta = obtener(URL_LLUVIA.format(lat=lat, lon=lon, desde=desde, hasta=hasta),
                   f"lluvia_open-meteo_{desde}_{hasta}.json", aviso)
    with open(ruta, encoding="utf-8") as f:
        horas = json.load(f)["hourly"]
    return {(date.fromisoformat(t[:10]), int(t[11:13])): (p or 0.0) >= UMBRAL_LLUVIA_MM
            for t, p in zip(horas["time"], horas["precipitation"])}


# ---------------------------------------------------------------------------
# Conversión al formato de la muestra
# ---------------------------------------------------------------------------

def convertir(entradas: Conteos, salidas: Conteos, lluvia: Dict[Tuple[date, int], bool],
              desde: date, hasta: date,
              codigos: Dict[str, Tuple[str, ...]] = CODIGOS_ESTACION) -> List[Dict[str, object]]:
    """Filas estación × fecha × hora con las columnas de la muestra (COLUMNAS_VALIDACIONES).
    Solo entran las estaciones con código y las horas de HORAS."""
    fechas = sorted({f for _, f, _ in entradas} | {f for _, f, _ in salidas})
    fechas = [f for f in fechas if desde <= f <= hasta]
    if not fechas:
        raise ValueError(f"Ningún día de los archivos está entre {desde} y {hasta}.")
    estaciones = sorted(e for e, cods in codigos.items() if cods)
    filas = []
    for f in fechas:
        for e in estaciones:
            for h in HORAS:
                filas.append({
                    "fecha": f.isoformat(),
                    "dia_semana": DIAS_SEMANA[f.weekday()],
                    "tipo_dia": tipo_de_dia(f),
                    "hora": h,
                    "estacion": e,
                    "lluvia": "si" if lluvia.get((f, h)) else "no",
                    "entradas": sum(entradas.get((c, f, h), 0) for c in codigos[e]),
                    "salidas": sum(salidas.get((c, f, h), 0) for c in codigos[e]),
                })
    return filas


@dataclass
class ResumenImportacion:
    filas: int
    estaciones: List[str]                  # con datos
    sin_datos: List[str]                   # estaciones de la base sin código (cerradas o nuevas)
    codigos_ausentes: List[str]            # códigos esperados que no aparecen en un archivo, o entradas huérfanas
    fechas: List[date]
    horas_con_lluvia: float
    entradas_sistema_por_dia: Dict[date, int]


def importar(entradas: str = URL_ENTRADAS, salidas: str = URL_SALIDAS, desde: date = INICIO_REAL,
             hasta: date = FIN_REAL, red: Optional[RedTransporte] = None, ruta: str = RUTA_REAL,
             aviso: Callable[[str], None] = print) -> ResumenImportacion:
    """Descarga (si hace falta) y convierte los reportes reales a datos/afluencia_transmilenio_real.csv."""
    red = red or RedTransporte()
    ent = leer_intervalos(obtener(entradas, aviso=aviso))
    sal = leer_intervalos(obtener(salidas, aviso=aviso))
    # Solo estaciones de la base de conocimiento (si se agrega una troncal, sus
    # estaciones quedan sin datos hasta que se añadan a CODIGOS_ESTACION).
    # Una estación sin datos en alguno de los dos archivos daría ceros engañosos: se excluye.
    huerfanas = sorted(set(CODIGOS_ESTACION) - set(red.estaciones))
    ausentes = [f"{e} (no está en la base de conocimiento)" for e in huerfanas]
    codigos = {}
    for e in red.estaciones:
        cods = CODIGOS_ESTACION.get(e, ())
        faltan = [f"{e} ({c}, {archivo})" for c in cods for archivo, rep in (("entradas", ent), ("salidas", sal))
                  if c not in rep.nombres]
        ausentes += faltan
        codigos[e] = () if faltan else cods
    lat, lon = red.coordenadas[CENTRO]
    lluvia = lluvia_por_hora(desde, hasta, lat, lon, aviso)
    filas = convertir(ent.conteos, sal.conteos, lluvia, desde, hasta, codigos)
    guardar_csv(filas, ruta, COLUMNAS_VALIDACIONES)
    fechas = sorted({date.fromisoformat(f["fecha"]) for f in filas})
    horas = [lluvia.get((f, h), False) for f in fechas for h in HORAS]
    return ResumenImportacion(
        len(filas), sorted(e for e, c in codigos.items() if c),
        sorted(e for e in red.estaciones if not CODIGOS_ESTACION.get(e)), ausentes, fechas,
        sum(horas) / len(horas), {f: ent.total_por_dia.get(f, 0) for f in fechas})


def cmd_importar(args) -> None:
    r = importar(args.entradas, args.salidas, args.desde, args.hasta,
                 aviso=lambda texto: consola.print(Text(texto, style="nota")))
    encabezado("Datos reales de TRANSMILENIO", ruta_relativa(RUTA_REAL, os.getcwd()))
    consola.print(pares([
        ("Filas", f"{r.filas} ({len(r.estaciones)} estaciones × {len(HORAS)} horas × {len(r.fechas)} días)"),
        ("Días", f"{r.fechas[0]} a {r.fechas[-1]}"),
        (f"Sin datos de recaudo ({len(r.sin_datos)})", ", ".join(r.sin_datos)),
        (f"Horas con lluvia (≥ {UMBRAL_LLUVIA_MM} mm)", f"{pct(r.horas_con_lluvia)} (Open-Meteo)"),
    ]))
    if r.codigos_ausentes:
        advertir(f"Estaciones excluidas: {', '.join(r.codigos_ausentes)}")
    subtitulo("Control: entradas de todo el sistema troncal")
    consola.print(Text("Comparables con la hoja de totales diarios del reporte.", style="nota"))
    consola.print(tabla_rich(["Fecha", "Entradas"], [[f, f"{r.entradas_sistema_por_dia[f]:,}".replace(",", ".")]
                                                     for f in r.fechas[:3]]))


def agregar_opciones_importar(sp) -> None:
    sp.add_argument("--entradas", default=URL_ENTRADAS,
                    help="URL o archivo XLSX de validaciones cada 15 min (por defecto, marzo de 2026)")
    sp.add_argument("--salidas", default=URL_SALIDAS,
                    help="URL o archivo XLSX de salidas cada 15 min (por defecto, marzo de 2026)")
    sp.add_argument("--desde", type=date.fromisoformat, default=INICIO_REAL, help="primer día (AAAA-MM-DD)")
    sp.add_argument("--hasta", type=date.fromisoformat, default=FIN_REAL, help="último día (AAAA-MM-DD)")
    sp.set_defaults(func=cmd_importar)
