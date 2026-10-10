"""
Evaluación de clasificadores.

- División estratificada entrenamiento/prueba y pliegues estratificados
  (cada parte conserva la proporción de clases).
- Matriz de confusión, exactitud, precisión, exhaustividad (recall) y F1.
- Validación cruzada para elegir la profundidad del árbol con la regla de
  "un error estándar" (Breiman et al., 1984): entre las profundidades cuya
  exactitud media está a menos de un error estándar de la mejor, se elige la
  menor, porque un árbol más pequeño se interpreta mejor y generaliza igual.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .arbol import ArbolDecision, Ejemplo


def division_estratificada(y: Sequence[str], prop_prueba: float = 0.3,
                           semilla: int = 42) -> Tuple[List[int], List[int]]:
    rng = random.Random(semilla)
    entrenamiento, prueba = [], []
    for clase in sorted(set(y)):
        indices = [i for i, c in enumerate(y) if c == clase]
        rng.shuffle(indices)
        corte = int(round(len(indices) * prop_prueba))
        prueba += indices[:corte]
        entrenamiento += indices[corte:]
    return sorted(entrenamiento), sorted(prueba)


def pliegues_estratificados(y: Sequence[str], k: int = 5, semilla: int = 42) -> List[List[int]]:
    rng = random.Random(semilla)
    pliegues: List[List[int]] = [[] for _ in range(k)]
    for clase in sorted(set(y)):
        indices = [i for i, c in enumerate(y) if c == clase]
        rng.shuffle(indices)
        for j, i in enumerate(indices):
            pliegues[j % k].append(i)
    return [sorted(p) for p in pliegues]


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

@dataclass
class Metricas:
    clases: List[str]
    matriz: List[List[int]]                 # filas = clase real, columnas = predicha
    exactitud: float
    por_clase: Dict[str, Dict[str, float]] = field(default_factory=dict)   # precision, recall, f1, soporte
    f1_macro: float = 0.0


def matriz_confusion(reales: Sequence[str], predichas: Sequence[str], clases: Sequence[str]) -> List[List[int]]:
    indice = {c: i for i, c in enumerate(clases)}
    m = [[0] * len(clases) for _ in clases]
    for r, p in zip(reales, predichas):
        m[indice[r]][indice[p]] += 1
    return m


def calcular_metricas(reales: Sequence[str], predichas: Sequence[str],
                      clases: Optional[Sequence[str]] = None) -> Metricas:
    if len(reales) != len(predichas) or not reales:
        raise ValueError("Se requieren listas no vacías de la misma longitud.")
    clases = list(clases) if clases else sorted(set(reales) | set(predichas))
    m = matriz_confusion(reales, predichas, clases)
    aciertos = sum(m[i][i] for i in range(len(clases)))
    resultado = Metricas(clases, m, aciertos / len(reales))
    for i, c in enumerate(clases):
        vp = m[i][i]
        predichos = sum(m[j][i] for j in range(len(clases)))
        soporte = sum(m[i])
        precision = vp / predichos if predichos else 0.0
        recall = vp / soporte if soporte else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        resultado.por_clase[c] = {"precision": precision, "recall": recall, "f1": f1, "soporte": soporte}
    resultado.f1_macro = sum(v["f1"] for v in resultado.por_clase.values()) / len(clases)
    return resultado


def exactitud(reales: Sequence[str], predichas: Sequence[str]) -> float:
    return sum(r == p for r, p in zip(reales, predichas)) / len(reales)


# ---------------------------------------------------------------------------
# Validación cruzada de la profundidad del árbol
# ---------------------------------------------------------------------------

@dataclass
class PuntoCurva:
    profundidad: int
    exactitud_entrenamiento: float
    exactitud_validacion: float
    error_estandar: float


def validar_profundidad(X: Sequence[Ejemplo], y: Sequence[str], atributos: Sequence[str],
                        profundidades: Sequence[int], k: int = 5, semilla: int = 42,
                        **parametros) -> Tuple[List[PuntoCurva], int]:
    """Exactitud media por profundidad en k pliegues. Devuelve la curva y la
    profundidad elegida con la regla de un error estándar."""
    pliegues = pliegues_estratificados(y, k, semilla)
    d_max = max(profundidades)
    ent: Dict[int, List[float]] = {d: [] for d in profundidades}
    val: Dict[int, List[float]] = {d: [] for d in profundidades}
    for j, pliegue in enumerate(pliegues):
        en_validacion = set(pliegue)
        idx_ent = [i for i in range(len(y)) if i not in en_validacion]
        X_ent, y_ent = [X[i] for i in idx_ent], [y[i] for i in idx_ent]
        X_val, y_val = [X[i] for i in pliegue], [y[i] for i in pliegue]
        # Un solo árbol profundo por pliegue; se evalúa truncado a cada profundidad
        arbol = ArbolDecision(profundidad_max=d_max, **parametros).entrenar(X_ent, y_ent, atributos)
        for d in profundidades:
            ent[d].append(exactitud(y_ent, arbol.predecir_lote(X_ent, d)))
            val[d].append(exactitud(y_val, arbol.predecir_lote(X_val, d)))
    curva = []
    for d in profundidades:
        media = sum(val[d]) / k
        desv = math.sqrt(sum((v - media) ** 2 for v in val[d]) / (k - 1)) if k > 1 else 0.0
        curva.append(PuntoCurva(d, sum(ent[d]) / k, media, desv / math.sqrt(k)))
    mejor = max(curva, key=lambda p: p.exactitud_validacion)
    elegida = min(p.profundidad for p in curva
                  if p.exactitud_validacion >= mejor.exactitud_validacion - mejor.error_estandar)
    return curva, elegida
