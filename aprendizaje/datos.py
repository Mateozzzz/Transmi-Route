"""
Dataset de muestra: afluencia (entradas y salidas) por estación y hora.

Papel de la muestra
-------------------
Las Actividades 3 y 4 usan como base los datos REALES de TRANSMILENIO
(entradas y salidas por estación cada 15 minutos, ver datos_reales.py). Esta
muestra sintética tiene exactamente las mismas columnas y se conserva:
- para trabajar sin conexión y en las pruebas automáticas;
- como "verdad conocida": cada estación tiene una vocación oculta con la que
  se generaron sus datos, así se puede comprobar que los métodos la recuperan.

    validaciones:  fecha, dia_semana, tipo_dia, hora, estacion, lluvia, entradas, salidas
    estaciones:    atributos de cada estación, derivados de la base de
                   conocimiento de la Actividad 2 (troncales, portal,
                   integración, coordenadas, distancia al centro)

Las dos tablas se unen por 'estacion', igual que los datos reales.

Modelo de generación (supuestos, ver README de las actividades)
--------------------------------------------------------------
- Cada estación tiene una VOCACIÓN oculta (residencial, empleo,
  educativa_ocio o mixta) según su ubicación y los atractores conocidos.
  La vocación determina la forma del perfil horario: las residenciales
  generan entradas en la mañana y salidas en la tarde; las de empleo, al revés.
  Ninguna estación es "pura": su perfil se mezcla (hasta 45 %) con otro uso.
- El volumen diario depende del tipo de estación (portal > integración >
  resto), de un factor propio de cada estación y del tipo de día.
- Ruido multiplicativo log-normal por hora y efecto de la lluvia (+10 %).
- Todo usa random.Random(semilla) y recorre listas ORDENADAS: la misma
  semilla produce exactamente el mismo archivo.
"""
from __future__ import annotations

import csv
import math
import os
import random
from datetime import date, timedelta
from functools import lru_cache
from typing import Dict, Iterable, List, Sequence, Tuple

from sistema.red import RedTransporte, distancia_km

DIR_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_DATOS = os.path.join(DIR_RAIZ, "datos")
RUTA_VALIDACIONES = os.path.join(DIR_DATOS, "afluencia_transmilenio_muestra.csv")
RUTA_REAL = os.path.join(DIR_DATOS, "afluencia_transmilenio_real.csv")
RUTA_ESTACIONES = os.path.join(DIR_DATOS, "estaciones.csv")

# Conjuntos de datos con las mismas columnas (opción --datos de las actividades)
RUTAS_DATOS = {"real": RUTA_REAL, "muestra": RUTA_VALIDACIONES}
NOMBRE_DATOS = {"real": "datos reales de TRANSMILENIO", "muestra": "muestra sintética"}
DESCRIPCION_DATOS = {
    "real": "entradas y salidas cada 15 minutos publicadas por TRANSMILENIO S.A., sumadas por hora "
            "(`datos/afluencia_transmilenio_real.csv`)",
    "muestra": "muestra sintética generada con semilla fija (`datos/afluencia_transmilenio_muestra.csv`)",
}

COLUMNAS_VALIDACIONES = ["fecha", "dia_semana", "tipo_dia", "hora", "estacion", "lluvia", "entradas", "salidas"]
COLUMNAS_ESTACIONES = ["estacion", "troncales", "latitud", "longitud", "es_portal", "es_integracion",
                       "num_troncales", "distancia_centro_km"]

INICIO = date(2026, 3, 2)          # lunes
HORAS = list(range(4, 23))         # franjas 4:00-4:59 ... 22:00-22:59
CENTRO = "Av. Jiménez"             # referencia para la distancia al centro
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Festivos de Colombia (Ley 51 de 1983, "Ley Emiliani"): fijos, trasladados al
# lunes siguiente y dependientes de la Pascua (días después del domingo de Pascua)
_FESTIVOS_FIJOS = {(1, 1): "Año Nuevo", (5, 1): "Día del Trabajo", (7, 20): "Independencia",
                   (8, 7): "Batalla de Boyacá", (12, 8): "Inmaculada Concepción", (12, 25): "Navidad"}
_FESTIVOS_AL_LUNES = {(1, 6): "Reyes Magos", (3, 19): "San José", (6, 29): "San Pedro y San Pablo",
                      (8, 15): "Asunción", (10, 12): "Día de la Raza", (11, 1): "Todos los Santos",
                      (11, 11): "Independencia de Cartagena"}
_FESTIVOS_PASCUA = {-3: "Jueves Santo", -2: "Viernes Santo", 43: "Ascensión", 64: "Corpus Christi",
                    71: "Sagrado Corazón"}

# --- Vocación de las estaciones (supuesto de uso del suelo, aproximado) -----------
ESTACIONES_EMPLEO = {
    "Calle 72", "Calle 76", "Héroes", "Calle 85", "Virrey", "Calle 100", "Calle 26", "Calle 22",
    "Calle 19", "Av. Jiménez", "Museo del Oro", "Tercer Milenio", "CAN", "Gobernación", "CAD",
    "El Tiempo - Maloka", "Salitre - El Greco", "Av. El Dorado", "Paloquemao", "Zona Industrial",
    "Puente Aranda",
}
ESTACIONES_EDUCATIVA_OCIO = {
    "U. Nacional", "Ciudad Universitaria", "Universidades", "Las Aguas", "Calle 45", "Marly",
    "Campín", "Movistar Arena", "Corferias",
}
DISTANCIA_RESIDENCIAL_KM = 7.5     # más lejos del centro -> vocación residencial
VOCACIONES = ["residencial", "empleo", "educativa_ocio", "mixta"]

# Picos del perfil horario de un día hábil: (hora central, ancho, altura)
_PICOS_HABIL: Dict[str, Dict[str, List[Tuple[float, float, float]]]] = {
    "residencial": {"entradas": [(6.0, 1.0, 1.0), (13.0, 2.5, 0.15), (18.0, 1.5, 0.20)],
                    "salidas": [(7.5, 1.2, 0.15), (13.0, 2.5, 0.15), (18.5, 1.5, 1.0)]},
    "empleo": {"entradas": [(7.0, 1.2, 0.20), (13.0, 2.0, 0.25), (17.5, 1.3, 1.0)],
               "salidas": [(7.0, 1.0, 1.0), (13.0, 2.0, 0.25), (18.0, 1.5, 0.20)]},
    "educativa_ocio": {"entradas": [(7.0, 1.0, 0.25), (12.5, 1.5, 0.60), (18.0, 1.5, 0.80), (21.0, 1.0, 0.35)],
                       "salidas": [(7.0, 1.0, 0.90), (10.0, 1.5, 0.45), (14.0, 1.5, 0.50), (18.0, 1.5, 0.35)]},
}
_PICOS_FIN_DE_SEMANA = [(12.5, 3.5, 1.0)]
_FONDO = 0.05

VOLUMEN_BASE = {"residencial": 9000, "empleo": 10000, "educativa_ocio": 8000, "mixta": 6500}
FACTOR_PORTAL, FACTOR_INTEGRACION = 3.5, 1.5
FACTOR_TIPO_DIA = {"habil": 1.0, "sabado": 0.55, "domingo_festivo": 0.32}
FACTOR_TIPO_DIA_OCIO = {"habil": 1.0, "sabado": 0.80, "domingo_festivo": 0.60}
FACTOR_DIA_SEMANA = [0.97, 1.0, 1.0, 1.0, 1.04, 1.0, 1.0]
EFECTO_LLUVIA = 1.10
RUIDO_HORA, RUIDO_ESTACION, RUIDO_SALIDAS = 0.12, 0.25, 0.08
MEZCLA_MAX = 0.45      # fracción máxima del perfil que proviene de otro uso del suelo


# ---------------------------------------------------------------------------
# Estaciones (catálogo derivado de la base de conocimiento)
# ---------------------------------------------------------------------------

def atributos_estaciones(red: RedTransporte) -> Dict[str, Dict[str, object]]:
    """Atributos de cada estación obtenidos de la base de conocimiento lógica."""
    centro = red.coordenadas[CENTRO]
    atributos: Dict[str, Dict[str, object]] = {}
    for e in red.estaciones:
        troncales = red.troncales_de(e)
        lat, lon = red.coordenadas[e]
        atributos[e] = {
            "estacion": e,
            "troncales": "|".join(troncales),
            "latitud": lat,
            "longitud": lon,
            "es_portal": "si" if red.kb.es_cierto("portal", e) else "no",
            "es_integracion": "si" if red.kb.es_cierto("estacion_de_integracion", e) else "no",
            "num_troncales": len(troncales),
            "distancia_centro_km": round(distancia_km(centro, (lat, lon)), 2),
        }
    return atributos


def vocacion_latente(estacion: str, atributos: Dict[str, object]) -> str:
    """Vocación OCULTA usada para generar los datos. No se escribe en el CSV:
    solo sirve para validar externamente el agrupamiento de la Actividad 4."""
    if estacion in ESTACIONES_EMPLEO:
        return "empleo"
    if estacion in ESTACIONES_EDUCATIVA_OCIO:
        return "educativa_ocio"
    if atributos["es_portal"] == "si" or float(atributos["distancia_centro_km"]) > DISTANCIA_RESIDENCIAL_KM:
        return "residencial"
    return "mixta"


# ---------------------------------------------------------------------------
# Perfiles horarios
# ---------------------------------------------------------------------------

def _curva(picos: Sequence[Tuple[float, float, float]]) -> List[float]:
    valores = [_FONDO + sum(a * math.exp(-((h - c) ** 2) / (2 * w ** 2)) for c, w, a in picos)
               for h in HORAS]
    total = sum(valores)
    return [v / total for v in valores]


def perfil_horario(vocacion: str, tipo_dia: str, sentido: str) -> List[float]:
    """Fracción del volumen diario que ocurre en cada hora de HORAS (suma 1)."""
    if vocacion == "mixta":
        habil = [(a + b) / 2 for a, b in zip(perfil_horario("residencial", "habil", sentido),
                                             perfil_horario("empleo", "habil", sentido))]
    else:
        habil = _curva(_PICOS_HABIL[vocacion][sentido])
    if tipo_dia == "habil":
        return habil
    plano = _curva(_PICOS_FIN_DE_SEMANA)
    return [0.7 * p + 0.3 * h for p, h in zip(plano, habil)]


def _pascua(anio: int) -> date:
    """Domingo de Pascua en el calendario gregoriano (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    h = (19 * a + b - b // 4 - (b - (b + 8) // 25 + 1) // 3 + 15) % 30
    semana = (32 + 2 * (b % 4) + 2 * (c // 4) - h - c % 4) % 7
    m = (a + 11 * h + 22 * semana) // 451
    n = h + semana - 7 * m + 114
    return date(anio, n // 31, n % 31 + 1)


@lru_cache(maxsize=None)
def festivos_colombia(anio: int) -> Dict[date, str]:
    festivos = {date(anio, m, d): nombre for (m, d), nombre in _FESTIVOS_FIJOS.items()}
    for (m, d), nombre in _FESTIVOS_AL_LUNES.items():
        f = date(anio, m, d)
        festivos.setdefault(f + timedelta(days=(7 - f.weekday()) % 7), nombre)
    pascua = _pascua(anio)
    for dias, nombre in _FESTIVOS_PASCUA.items():
        festivos.setdefault(pascua + timedelta(days=dias), nombre)
    return dict(sorted(festivos.items()))


def tipo_de_dia(d: date) -> str:
    if d in festivos_colombia(d.year) or d.weekday() == 6:
        return "domingo_festivo"
    return "sabado" if d.weekday() == 5 else "habil"


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------

def generar_dataset(red: RedTransporte, dias: int = 28, semilla: int = 42,
                    inicio: date = INICIO) -> List[Dict[str, object]]:
    """Genera las filas de validaciones (una por estación, fecha y hora)."""
    if dias < 1:
        raise ValueError("El número de días debe ser positivo.")
    rng = random.Random(semilla)
    atributos = atributos_estaciones(red)
    estaciones = sorted(atributos)

    base = {(voc, td, s): perfil_horario(voc, td, s)
            for voc in VOCACIONES for td in FACTOR_TIPO_DIA for s in ("entradas", "salidas")}

    # Características fijas de cada estación (en orden alfabético -> determinista)
    volumen: Dict[str, float] = {}
    balance_salidas: Dict[str, float] = {}
    vocacion: Dict[str, str] = {}
    perfiles: Dict[Tuple[str, str, str], List[float]] = {}
    for e in estaciones:
        a = atributos[e]
        vocacion[e] = vocacion_latente(e, a)
        v = VOLUMEN_BASE[vocacion[e]]
        if a["es_portal"] == "si":
            v *= FACTOR_PORTAL
        elif a["es_integracion"] == "si":
            v *= FACTOR_INTEGRACION
        volumen[e] = v * rng.lognormvariate(0, RUIDO_ESTACION)
        balance_salidas[e] = rng.lognormvariate(0, RUIDO_SALIDAS)
        # Ninguna estación es "pura": su perfil se mezcla en parte con otro uso
        # (las mixtas se inclinan hacia lo residencial o hacia el empleo)
        otro = rng.choice(["residencial", "empleo"]) if vocacion[e] == "mixta" else "mixta"
        mezcla = rng.uniform(0.0, MEZCLA_MAX)
        for td in FACTOR_TIPO_DIA:
            for s in ("entradas", "salidas"):
                perfiles[(e, td, s)] = [(1 - mezcla) * p + mezcla * q
                                        for p, q in zip(base[(vocacion[e], td, s)], base[(otro, td, s)])]

    filas: List[Dict[str, object]] = []
    for n in range(dias):
        d = inicio + timedelta(days=n)
        td = tipo_de_dia(d)
        # Lluvia en toda la ciudad, más probable en la tarde (temporada de lluvias)
        lluvia = {h: rng.random() < (0.40 if 13 <= h <= 18 else 0.06) for h in HORAS}
        for e in estaciones:
            factor_dia = (FACTOR_TIPO_DIA_OCIO if vocacion[e] == "educativa_ocio" else FACTOR_TIPO_DIA)[td]
            total_dia = volumen[e] * factor_dia * FACTOR_DIA_SEMANA[d.weekday()]
            p_ent = perfiles[(e, td, "entradas")]
            p_sal = perfiles[(e, td, "salidas")]
            for i, h in enumerate(HORAS):
                clima = EFECTO_LLUVIA if lluvia[h] else 1.0
                entradas = total_dia * p_ent[i] * clima * rng.lognormvariate(0, RUIDO_HORA)
                salidas = total_dia * balance_salidas[e] * p_sal[i] * clima * rng.lognormvariate(0, RUIDO_HORA)
                filas.append({
                    "fecha": d.isoformat(),
                    "dia_semana": DIAS_SEMANA[d.weekday()],
                    "tipo_dia": td,
                    "hora": h,
                    "estacion": e,
                    "lluvia": "si" if lluvia[h] else "no",
                    "entradas": int(round(entradas)),
                    "salidas": int(round(salidas)),
                })
    return filas


# ---------------------------------------------------------------------------
# Lectura y escritura
# ---------------------------------------------------------------------------

def guardar_csv(filas: Iterable[Dict[str, object]], ruta: str, columnas: Sequence[str]) -> None:
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columnas), lineterminator="\n")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)


def generar_archivos(dias: int = 28, semilla: int = 42, red: RedTransporte = None) -> Tuple[int, int]:
    """Genera y guarda los dos CSV en /datos. Devuelve (filas, estaciones)."""
    red = red or RedTransporte()
    atributos = atributos_estaciones(red)
    filas = generar_dataset(red, dias, semilla)
    guardar_csv(filas, RUTA_VALIDACIONES, COLUMNAS_VALIDACIONES)
    guardar_csv((atributos[e] for e in sorted(atributos)), RUTA_ESTACIONES, COLUMNAS_ESTACIONES)
    return len(filas), len(atributos)


def cargar_dataset(ruta: str = RUTA_VALIDACIONES) -> List[Dict[str, object]]:
    if not os.path.exists(ruta):
        raise ValueError(f"No existe {ruta}. Ejecute primero el comando 'importar' (datos reales) "
                         "o 'generar' (muestra sintética).")
    with open(ruta, encoding="utf-8", newline="") as f:
        filas: List[Dict[str, object]] = list(csv.DictReader(f))
    for fila in filas:
        for col in ("hora", "entradas", "salidas"):
            fila[col] = int(fila[col])
    return filas


def unir_atributos(filas: Iterable[Dict[str, object]],
                   atributos: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    """Une cada validación con los atributos de su estación (join por 'estacion')."""
    unidas = []
    for fila in filas:
        if fila["estacion"] not in atributos:
            raise ValueError(f"Estación sin atributos en el catálogo: {fila['estacion']}")
        unidas.append({**fila, **atributos[fila["estacion"]]})
    return unidas
