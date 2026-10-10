"""
Técnicas de agrupamiento (Palma Méndez, 2008, cap. 16).

- estandarizar:        puntuación z por atributo (media 0, desviación 1), para
                       que ningún atributo domine la distancia por su escala.
- kmedias:             k-medias (MacQueen, 1967) con inicialización k-medias++
                       (Arthur y Vassilvitskii, 2007) y varios reinicios; se
                       conserva el de menor suma de errores cuadráticos (SSE).
- jerarquico / cortar: agrupamiento jerárquico aglomerativo con la fórmula de
                       Lance-Williams (enlace simple, completo, promedio o Ward).
- silueta:             coeficiente de silueta (Rousseeuw, 1987), entre -1 y 1.
- indice_rand_ajustado: concordancia entre dos particiones (Hubert y Arabie,
                       1985): 1 = idénticas, ~0 = como al azar.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

Vector = List[float]
ENLACES = ("simple", "completo", "promedio", "ward")


def distancia2(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def estandarizar(X: Sequence[Sequence[float]]) -> Tuple[List[Vector], List[float], List[float]]:
    """Devuelve (Z, medias, desviaciones). Desviación poblacional; si es 0 se usa 1."""
    n, d = len(X), len(X[0])
    medias = [sum(x[j] for x in X) / n for j in range(d)]
    desv = [math.sqrt(sum((x[j] - medias[j]) ** 2 for x in X) / n) or 1.0 for j in range(d)]
    return [[(x[j] - medias[j]) / desv[j] for j in range(d)] for x in X], medias, desv


def renumerar(etiquetas: Sequence[int]) -> List[int]:
    """Numera los grupos por orden de primera aparición (0, 1, 2, ...)."""
    mapa: Dict[int, int] = {}
    return [mapa.setdefault(e, len(mapa)) for e in etiquetas]


def centroides(X: Sequence[Sequence[float]], etiquetas: Sequence[int]) -> List[Vector]:
    k = max(etiquetas) + 1
    d = len(X[0])
    sumas = [[0.0] * d for _ in range(k)]
    tamanos = [0] * k
    for x, e in zip(X, etiquetas):
        tamanos[e] += 1
        for j in range(d):
            sumas[e][j] += x[j]
    return [[s / t for s in fila] if t else fila for fila, t in zip(sumas, tamanos)]


def sse(X: Sequence[Sequence[float]], etiquetas: Sequence[int]) -> float:
    """Suma de distancias cuadráticas de cada punto al centroide de su grupo."""
    c = centroides(X, etiquetas)
    return sum(distancia2(x, c[e]) for x, e in zip(X, etiquetas))


# ---------------------------------------------------------------------------
# k-medias
# ---------------------------------------------------------------------------

@dataclass
class ResultadoKMedias:
    etiquetas: List[int]
    centroides: List[Vector]
    sse: float
    iteraciones: int


def _kmedias_pp(X: Sequence[Sequence[float]], k: int, rng: random.Random) -> List[Vector]:
    """k-medias++: cada nuevo centro se elige con probabilidad proporcional a D(x)^2."""
    centros = [list(X[rng.randrange(len(X))])]
    d2 = [distancia2(x, centros[0]) for x in X]
    while len(centros) < k:
        total = sum(d2)
        if total == 0:
            centros.append(list(X[rng.randrange(len(X))]))
            continue
        umbral, acum = rng.random() * total, 0.0
        for i, v in enumerate(d2):
            acum += v
            if acum >= umbral:
                break
        centros.append(list(X[i]))
        d2 = [min(a, distancia2(x, centros[-1])) for a, x in zip(d2, X)]
    return centros


def _lloyd(X: Sequence[Sequence[float]], centros: List[Vector], max_iter: int) -> ResultadoKMedias:
    k = len(centros)
    etiquetas = [-1] * len(X)
    for it in range(1, max_iter + 1):
        nuevas = [min(range(k), key=lambda c: distancia2(x, centros[c])) for x in X]
        # Grupo vacío: se le asigna el punto más lejano de su centro
        for c in range(k):
            if c not in nuevas:
                lejano = max(range(len(X)), key=lambda i: distancia2(X[i], centros[nuevas[i]]))
                nuevas[lejano] = c
        if nuevas == etiquetas:
            break
        etiquetas = nuevas
        centros = centroides(X, etiquetas)
    return ResultadoKMedias(etiquetas, centros, sse(X, etiquetas), it)


def kmedias(X: Sequence[Sequence[float]], k: int, semilla: int = 0, n_init: int = 10,
            max_iter: int = 100) -> ResultadoKMedias:
    if not 1 <= k <= len(X):
        raise ValueError(f"k debe estar entre 1 y {len(X)}")
    rng = random.Random(semilla)
    mejor = None
    for _ in range(n_init):
        r = _lloyd(X, _kmedias_pp(X, k, rng), max_iter)
        if mejor is None or r.sse < mejor.sse - 1e-12:
            mejor = r
    etiquetas = renumerar(mejor.etiquetas)
    return ResultadoKMedias(etiquetas, centroides(X, etiquetas), mejor.sse, mejor.iteraciones)


# ---------------------------------------------------------------------------
# Agrupamiento jerárquico aglomerativo
# ---------------------------------------------------------------------------

Fusion = Tuple[int, int, float, int]   # (grupo a, grupo b, distancia, tamaño), ids como en scipy


def jerarquico(X: Sequence[Sequence[float]], enlace: str = "ward") -> List[Fusion]:
    """Une repetidamente los dos grupos más cercanos y actualiza las distancias con
    la fórmula de Lance-Williams. Las hojas son 0..n-1 y el grupo creado en la
    fusión i recibe el id n+i. Con Ward se trabaja con distancias euclidianas al
    cuadrado y se reporta la raíz (igual que scipy)."""
    if enlace not in ENLACES:
        raise ValueError(f"Enlace inválido: {enlace}. Opciones: {', '.join(ENLACES)}")
    n = len(X)
    cuadrado = enlace == "ward"
    D: Dict[int, Dict[int, float]] = {i: {} for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            d = distancia2(X[i], X[j])
            D[i][j] = D[j][i] = d if cuadrado else math.sqrt(d)
    tamano = {i: 1 for i in range(n)}
    fusiones: List[Fusion] = []
    for paso in range(n - 1):
        activos = sorted(D)
        # Par más cercano (desempate determinista por ids)
        a, b = min(((i, j) for i in activos for j in activos if i < j), key=lambda p: (D[p[0]][p[1]], p))
        dab = D[a][b]
        nuevo, na, nb = n + paso, tamano[a], tamano[b]
        D[nuevo] = {}
        for c in activos:
            if c in (a, b):
                continue
            nc, dac, dbc = tamano[c], D[a][c], D[b][c]
            if enlace == "simple":
                d = min(dac, dbc)
            elif enlace == "completo":
                d = max(dac, dbc)
            elif enlace == "promedio":
                d = (na * dac + nb * dbc) / (na + nb)
            else:  # ward
                d = ((na + nc) * dac + (nb + nc) * dbc - nc * dab) / (na + nb + nc)
            D[nuevo][c] = D[c][nuevo] = d
        for c in (a, b):
            for otro in D.pop(c):
                if otro in D:
                    D[otro].pop(c, None)
        tamano[nuevo] = na + nb
        fusiones.append((a, b, math.sqrt(dab) if cuadrado else dab, na + nb))
    return fusiones


def cortar(fusiones: Sequence[Fusion], n: int, k: int) -> List[int]:
    """Etiquetas al detener las fusiones cuando quedan k grupos."""
    if not 1 <= k <= n:
        raise ValueError(f"k debe estar entre 1 y {n}")
    padre = list(range(n + len(fusiones)))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for paso, (a, b, _, _) in enumerate(fusiones[: n - k]):
        ra, rb = raiz(a), raiz(b)
        padre[ra] = padre[rb] = n + paso
    return renumerar([raiz(i) for i in range(n)])


def altura_de_corte(fusiones: Sequence[Fusion], n: int, k: int) -> float:
    """Altura entre la última fusión hecha y la primera omitida al cortar en k grupos."""
    hechas = n - k
    abajo = fusiones[hechas - 1][2] if hechas > 0 else 0.0
    arriba = fusiones[hechas][2] if hechas < len(fusiones) else abajo
    return (abajo + arriba) / 2


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def silueta_por_muestra(X: Sequence[Sequence[float]], etiquetas: Sequence[int]) -> List[float]:
    """s(i) = (b - a) / max(a, b); a = distancia media a su grupo, b = al grupo vecino más cercano."""
    grupos = sorted(set(etiquetas))
    if len(grupos) < 2:
        raise ValueError("La silueta requiere al menos 2 grupos.")
    miembros = {g: [i for i, e in enumerate(etiquetas) if e == g] for g in grupos}
    valores = []
    for i, x in enumerate(X):
        propio = miembros[etiquetas[i]]
        if len(propio) == 1:
            valores.append(0.0)
            continue
        a = sum(math.sqrt(distancia2(x, X[j])) for j in propio if j != i) / (len(propio) - 1)
        b = min(sum(math.sqrt(distancia2(x, X[j])) for j in miembros[g]) / len(miembros[g])
                for g in grupos if g != etiquetas[i])
        valores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return valores


def silueta(X: Sequence[Sequence[float]], etiquetas: Sequence[int]) -> float:
    valores = silueta_por_muestra(X, etiquetas)
    return sum(valores) / len(valores)


def tabla_contingencia(a: Sequence, b: Sequence) -> Dict[Tuple[object, object], int]:
    tabla: Dict[Tuple[object, object], int] = {}
    for x, y in zip(a, b):
        tabla[(x, y)] = tabla.get((x, y), 0) + 1
    return tabla


def indice_rand_ajustado(a: Sequence, b: Sequence) -> float:
    if len(a) != len(b):
        raise ValueError("Las particiones deben tener la misma longitud.")
    comb2 = lambda m: m * (m - 1) / 2
    n = len(a)
    tabla = tabla_contingencia(a, b)
    filas: Dict[object, int] = {}
    cols: Dict[object, int] = {}
    for (x, y), c in tabla.items():
        filas[x] = filas.get(x, 0) + c
        cols[y] = cols.get(y, 0) + c
    indice = sum(comb2(c) for c in tabla.values())
    suma_f = sum(comb2(c) for c in filas.values())
    suma_c = sum(comb2(c) for c in cols.values())
    esperado = suma_f * suma_c / comb2(n) if n > 1 else 0.0
    maximo = (suma_f + suma_c) / 2
    if maximo == esperado:
        return 1.0
    return (indice - esperado) / (maximo - esperado)
