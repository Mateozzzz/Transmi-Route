"""
Aprendizaje de árboles y reglas de decisión (Palma Méndez, 2008, cap. 17).

ArbolDecision
-------------
Inducción descendente (top-down) al estilo ID3 / C4.5 (Quinlan):

    H(S)            = -Σ p_c · log2(p_c)                     entropía
    Ganancia(S, A)  = H(S) - Σ |S_v|/|S| · H(S_v)             ID3
    Razón(S, A)     = Ganancia(S, A) / InfoDivisión(S, A)     C4.5

- Atributos categóricos: división múltiple (una rama por valor).
- Atributos numéricos: división binaria  A ≤ umbral  /  A > umbral, con el
  umbral en el punto medio entre dos valores consecutivos (C4.5).
- Pre-poda: profundidad máxima, mínimo de ejemplos por hoja y ganancia mínima.
- Post-proceso: si todas las hojas de un subárbol predicen la misma clase,
  el subárbol se reemplaza por una hoja (no cambia ninguna predicción).

Cada nodo guarda su clase mayoritaria, por lo que el árbol puede predecir
"truncado" a cualquier profundidad: un árbol crecido hasta profundidad D
responde exactamente igual que uno entrenado con profundidad_max = d ≤ D.
Eso permite elegir la profundidad por validación cruzada entrenando un solo
árbol por pliegue.

Cada camino raíz-hoja se convierte en una regla SI ... ENTONCES ... con su
soporte y confianza.

ZeroR y OneR (Holte, 1993) sirven como líneas base.
"""
from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

Valor = Union[str, int, float]
Ejemplo = Dict[str, Valor]

NUMERICO, CATEGORICO = "numerico", "categorico"
CRITERIOS = ("ganancia", "razon")


def entropia(conteos: Iterable[int]) -> float:
    conteos = [c for c in conteos if c > 0]
    n = sum(conteos)
    return -sum(c / n * math.log2(c / n) for c in conteos) if n else 0.0


def inferir_tipos(X: Sequence[Ejemplo], atributos: Sequence[str]) -> Dict[str, str]:
    """Numérico si todos los valores son int/float; si no, categórico."""
    return {a: NUMERICO if all(isinstance(x[a], (int, float)) and not isinstance(x[a], bool) for x in X)
            else CATEGORICO for a in atributos}


def _mayoritaria(conteos: Dict[str, int], clases: Sequence[str]) -> str:
    # Desempate determinista: el orden de 'clases'
    return max(clases, key=lambda c: (conteos.get(c, 0), -clases.index(c)))


def _formatear_numero(v: float) -> str:
    return f"{v:g}" if abs(v) >= 1 or v == 0 else f"{v:.4g}"


# ---------------------------------------------------------------------------
# Nodos, condiciones y reglas
# ---------------------------------------------------------------------------

@dataclass
class Nodo:
    clase: str                                   # clase mayoritaria del nodo
    conteos: Dict[str, int]
    profundidad: int = 0
    atributo: Optional[str] = None               # None -> hoja
    umbral: Optional[float] = None               # solo atributos numéricos
    hijos: Dict[str, "Nodo"] = field(default_factory=dict)   # "<=" / ">" o valor categórico
    ganancia: float = 0.0

    @property
    def es_hoja(self) -> bool:
        return self.atributo is None

    @property
    def n(self) -> int:
        return sum(self.conteos.values())

    @property
    def confianza(self) -> float:
        return self.conteos.get(self.clase, 0) / self.n if self.n else 0.0

    def a_dict(self) -> Dict[str, object]:
        d: Dict[str, object] = {"clase": self.clase, "conteos": self.conteos, "profundidad": self.profundidad}
        if not self.es_hoja:
            d.update(atributo=self.atributo, umbral=self.umbral, ganancia=round(self.ganancia, 6),
                     hijos={k: h.a_dict() for k, h in self.hijos.items()})
        return d

    @staticmethod
    def desde_dict(d: Dict[str, object]) -> "Nodo":
        nodo = Nodo(d["clase"], dict(d["conteos"]), d["profundidad"])
        if "atributo" in d:
            nodo.atributo, nodo.umbral, nodo.ganancia = d["atributo"], d["umbral"], d["ganancia"]
            nodo.hijos = {k: Nodo.desde_dict(h) for k, h in d["hijos"].items()}
        return nodo


@dataclass(frozen=True)
class Condicion:
    atributo: str
    operador: str      # "=", "<=", ">"
    valor: Valor

    def cumple(self, x: Ejemplo) -> bool:
        v = x.get(self.atributo)
        if self.operador == "=":
            return str(v) == str(self.valor)
        return v <= self.valor if self.operador == "<=" else v > self.valor

    def __str__(self) -> str:
        valor = _formatear_numero(self.valor) if isinstance(self.valor, float) else self.valor
        return f"{self.atributo} {'≤' if self.operador == '<=' else self.operador} {valor}"


@dataclass
class ReglaDecision:
    condiciones: List[Condicion]
    clase: str
    soporte: int           # ejemplos de entrenamiento que cubre
    confianza: float       # fracción de ellos que son de la clase predicha

    def cubre(self, x: Ejemplo) -> bool:
        return all(c.cumple(x) for c in self.condiciones)

    def texto_condiciones(self) -> str:
        """Une las condiciones sobre un mismo atributo numérico en un intervalo."""
        partes: List[str] = []
        vistos = set()
        for c in self.condiciones:
            if c.atributo in vistos:
                continue
            vistos.add(c.atributo)
            mismas = [d for d in self.condiciones if d.atributo == c.atributo]
            if c.operador == "=":
                partes.append(str(mismas[-1]))
                continue
            inf = max((d.valor for d in mismas if d.operador == ">"), default=None)
            sup = min((d.valor for d in mismas if d.operador == "<="), default=None)
            if inf is not None and sup is not None:
                partes.append(f"{_formatear_numero(inf)} < {c.atributo} ≤ {_formatear_numero(sup)}")
            elif inf is not None:
                partes.append(f"{c.atributo} > {_formatear_numero(inf)}")
            else:
                partes.append(f"{c.atributo} ≤ {_formatear_numero(sup)}")
        return " Y ".join(partes) if partes else "(siempre)"

    def __str__(self) -> str:
        return (f"SI {self.texto_condiciones()} ENTONCES {self.clase}  "
                f"[soporte {self.soporte}, confianza {self.confianza:.0%}]")


# ---------------------------------------------------------------------------
# Árbol de decisión
# ---------------------------------------------------------------------------

class ArbolDecision:
    def __init__(self, criterio: str = "ganancia", profundidad_max: Optional[int] = None,
                 min_muestras_hoja: int = 1, ganancia_min: float = 1e-6):
        if criterio not in CRITERIOS:
            raise ValueError(f"Criterio inválido: {criterio}. Opciones: {', '.join(CRITERIOS)}")
        self.criterio = criterio
        self.profundidad_max = profundidad_max
        self.min_muestras_hoja = max(1, min_muestras_hoja)
        self.ganancia_min = ganancia_min
        self.raiz: Optional[Nodo] = None
        self.atributos: List[str] = []
        self.tipos: Dict[str, str] = {}
        self.clases: List[str] = []

    # --- entrenamiento ----------------------------------------------------------
    def entrenar(self, X: Sequence[Ejemplo], y: Sequence[str], atributos: Sequence[str],
                 tipos: Optional[Dict[str, str]] = None, clases: Optional[Sequence[str]] = None) -> "ArbolDecision":
        if not X or len(X) != len(y):
            raise ValueError("Se requieren ejemplos y etiquetas de la misma longitud.")
        self.atributos = list(atributos)
        self.tipos = dict(tipos) if tipos else inferir_tipos(X, self.atributos)
        self.clases = list(clases) if clases else sorted(set(y))
        indice_clase = {c: i for i, c in enumerate(self.clases)}
        # Representación por columnas: más rápida que recorrer diccionarios
        self._columnas = {a: [x[a] for x in X] for a in self.atributos}
        self._y = [indice_clase[c] for c in y]
        self.raiz = self._crecer(list(range(len(X))), 0)
        self._simplificar(self.raiz)
        del self._columnas, self._y
        return self

    def _conteos(self, indices: Sequence[int]) -> List[int]:
        cuenta = [0] * len(self.clases)
        for i in indices:
            cuenta[self._y[i]] += 1
        return cuenta

    def _nodo(self, cuenta: List[int], profundidad: int) -> Nodo:
        conteos = {c: n for c, n in zip(self.clases, cuenta) if n}
        return Nodo(_mayoritaria(conteos, self.clases), conteos, profundidad)

    def _crecer(self, indices: List[int], profundidad: int) -> Nodo:
        cuenta = self._conteos(indices)
        nodo = self._nodo(cuenta, profundidad)
        n = len(indices)
        if (max(cuenta) == n or n < 2 * self.min_muestras_hoja
                or (self.profundidad_max is not None and profundidad >= self.profundidad_max)):
            return nodo
        mejor = self._mejor_division(indices, entropia(cuenta))
        if mejor is None:
            return nodo
        atributo, umbral, ganancia, particion = mejor
        nodo.atributo, nodo.umbral, nodo.ganancia = atributo, umbral, ganancia
        for rama, sub in particion.items():
            nodo.hijos[rama] = self._crecer(sub, profundidad + 1)
        return nodo

    def _mejor_division(self, indices: List[int], h_padre: float):
        n = len(indices)
        y, k, minimo = self._y, len(self.clases), self.min_muestras_hoja
        candidatos = []   # (atributo, umbral, ganancia, razon)
        for a in self.atributos:
            col = self._columnas[a]
            # Un solo recorrido: conteo de clases por cada valor del atributo
            por_valor: Dict[Valor, List[int]] = {}
            for i in indices:
                c = por_valor.get(col[i])
                if c is None:
                    c = por_valor[col[i]] = [0] * k
                c[y[i]] += 1
            if len(por_valor) < 2:
                continue
            if self.tipos[a] == CATEGORICO:
                tamanos = [sum(c) for c in por_valor.values()]
                if min(tamanos) < minimo:
                    continue
                h_hijos = sum(t / n * entropia(c) for t, c in zip(tamanos, por_valor.values()))
                info = entropia(tamanos)
                candidatos.append((a, None, h_padre - h_hijos, (h_padre - h_hijos) / info if info else 0.0))
                continue
            # Numérico: barrido de umbrales sobre los valores distintos ordenados
            valores = sorted(por_valor)
            total = [sum(c[j] for c in por_valor.values()) for j in range(k)]
            izq, n_izq = [0] * k, 0
            mejor_local = None
            for v_actual, v_sig in zip(valores, valores[1:]):
                for j, c in enumerate(por_valor[v_actual]):
                    izq[j] += c
                n_izq += sum(por_valor[v_actual])
                n_der = n - n_izq
                if n_izq < minimo or n_der < minimo:
                    continue
                der = [t - l for t, l in zip(total, izq)]
                h_hijos = n_izq / n * entropia(izq) + n_der / n * entropia(der)
                ganancia = h_padre - h_hijos
                if mejor_local is None or ganancia > mejor_local[2] + 1e-12:
                    info = entropia([n_izq, n_der])
                    mejor_local = (a, (v_actual + v_sig) / 2, ganancia, ganancia / info if info else 0.0)
            if mejor_local:
                candidatos.append(mejor_local)
        candidatos = [c for c in candidatos if c[2] > self.ganancia_min]
        if not candidatos:
            return None
        if self.criterio == "ganancia":
            atributo, umbral, ganancia, _ = max(candidatos, key=lambda c: c[2])
        else:
            # C4.5: mayor razón de ganancia entre los que tienen ganancia >= promedio
            promedio = sum(c[2] for c in candidatos) / len(candidatos)
            atributo, umbral, ganancia, _ = max((c for c in candidatos if c[2] >= promedio - 1e-12),
                                                key=lambda c: c[3])
        col = self._columnas[atributo]
        particion: Dict[str, List[int]] = {}
        if umbral is None:
            for i in indices:
                particion.setdefault(str(col[i]), []).append(i)
            particion = dict(sorted(particion.items()))
        else:
            particion = {"<=": [i for i in indices if col[i] <= umbral],
                         ">": [i for i in indices if col[i] > umbral]}
        return atributo, umbral, ganancia, particion

    def _simplificar(self, nodo: Nodo) -> None:
        """Si todas las hojas bajo un nodo predicen la misma clase, el nodo se vuelve hoja."""
        if nodo.es_hoja:
            return
        for h in nodo.hijos.values():
            self._simplificar(h)
        if all(h.es_hoja and h.clase == nodo.clase for h in nodo.hijos.values()):
            nodo.atributo, nodo.umbral, nodo.hijos, nodo.ganancia = None, None, {}, 0.0

    # --- predicción -------------------------------------------------------------
    def _rama(self, nodo: Nodo, x: Ejemplo) -> Optional[str]:
        v = x.get(nodo.atributo)
        if nodo.umbral is not None:
            return "<=" if v <= nodo.umbral else ">"
        return str(v) if str(v) in nodo.hijos else None   # valor no visto -> se queda en el nodo

    def _recorrer(self, x: Ejemplo, profundidad: Optional[int] = None) -> List[Tuple[Nodo, Optional[str]]]:
        if self.raiz is None:
            raise ValueError("El árbol no ha sido entrenado.")
        camino, nodo = [], self.raiz
        while not nodo.es_hoja and (profundidad is None or nodo.profundidad < profundidad):
            rama = self._rama(nodo, x)
            camino.append((nodo, rama))
            if rama is None:
                return camino
            nodo = nodo.hijos[rama]
        camino.append((nodo, None))
        return camino

    def predecir(self, x: Ejemplo, profundidad: Optional[int] = None) -> str:
        return self._recorrer(x, profundidad)[-1][0].clase

    def predecir_lote(self, X: Sequence[Ejemplo], profundidad: Optional[int] = None) -> List[str]:
        return [self.predecir(x, profundidad) for x in X]

    def explicar(self, x: Ejemplo) -> ReglaDecision:
        """Regla (camino raíz-hoja) que se activa para el ejemplo x."""
        camino = self._recorrer(x)
        condiciones = [self._condicion(nodo, rama) for nodo, rama in camino[:-1] if rama is not None]
        hoja = camino[-1][0]
        return ReglaDecision(condiciones, hoja.clase, hoja.n, hoja.confianza)

    @staticmethod
    def _condicion(nodo: Nodo, rama: str) -> Condicion:
        if nodo.umbral is not None:
            return Condicion(nodo.atributo, rama, nodo.umbral)
        return Condicion(nodo.atributo, "=", rama)

    # --- reglas e interpretación ------------------------------------------------
    def extraer_reglas(self) -> List[ReglaDecision]:
        """Una regla por hoja. Ordenadas por clase y luego por soporte."""
        reglas: List[ReglaDecision] = []

        def visitar(nodo: Nodo, condiciones: List[Condicion]) -> None:
            if nodo.es_hoja:
                reglas.append(ReglaDecision(condiciones, nodo.clase, nodo.n, nodo.confianza))
                return
            for rama, hijo in nodo.hijos.items():
                visitar(hijo, condiciones + [self._condicion(nodo, rama)])

        visitar(self.raiz, [])
        reglas.sort(key=lambda r: (self.clases.index(r.clase), -r.soporte))
        return reglas

    def importancia(self) -> Dict[str, float]:
        """Ganancia total ponderada por el tamaño de cada nodo, normalizada a 1."""
        total: Dict[str, float] = {a: 0.0 for a in self.atributos}

        def visitar(nodo: Nodo) -> None:
            if not nodo.es_hoja:
                total[nodo.atributo] += nodo.n * nodo.ganancia
                for h in nodo.hijos.values():
                    visitar(h)

        visitar(self.raiz)
        suma = sum(total.values())
        return {a: (v / suma if suma else 0.0) for a, v in sorted(total.items(), key=lambda kv: -kv[1])}

    def contar(self) -> Tuple[int, int, int]:
        """(nodos, hojas, profundidad real)."""
        nodos = hojas = prof = 0
        pila = [self.raiz]
        while pila:
            nodo = pila.pop()
            nodos += 1
            prof = max(prof, nodo.profundidad)
            if nodo.es_hoja:
                hojas += 1
            pila.extend(nodo.hijos.values())
        return nodos, hojas, prof

    @staticmethod
    def _texto_rama(nodo: Nodo, rama: str) -> str:
        if nodo.umbral is not None:
            simbolo = "≤" if rama == "<=" else ">"
            return f"{nodo.atributo} {simbolo} {_formatear_numero(nodo.umbral)}"
        return f"{nodo.atributo} = {rama}"

    def a_texto(self, profundidad_max: Optional[int] = None) -> str:
        """Árbol en texto, una línea por rama."""
        r = self.raiz
        lineas = [f"(raíz) n={r.n}  ->  {r.clase} {r.confianza:.0%}"]

        def visitar(nodo: Nodo, prefijo: str) -> None:
            ramas = list(nodo.hijos.items())
            for i, (rama, hijo) in enumerate(ramas):
                ultimo = i == len(ramas) - 1
                conector = "└── " if ultimo else "├── "
                truncado = profundidad_max is not None and hijo.profundidad >= profundidad_max and not hijo.es_hoja
                resumen = f"{hijo.clase} ({hijo.confianza:.0%}, n={hijo.n})"
                if hijo.es_hoja:
                    lineas.append(f"{prefijo}{conector}{self._texto_rama(nodo, rama)}: {resumen}")
                else:
                    extra = " ..." if truncado else ""
                    lineas.append(f"{prefijo}{conector}{self._texto_rama(nodo, rama)}  [{resumen}]{extra}")
                    if not truncado:
                        visitar(hijo, prefijo + ("    " if ultimo else "│   "))

        visitar(r, "")
        return "\n".join(lineas)

    def a_mermaid(self, niveles: int = 3) -> str:
        """Diagrama Mermaid de los primeros niveles (GitHub lo dibuja en el README)."""
        lineas = ["flowchart TD"]
        contador = [0]

        def nuevo_id() -> str:
            contador[0] += 1
            return f"n{contador[0]}"

        def visitar(nodo: Nodo, ident: str) -> None:
            if nodo.es_hoja or nodo.profundidad >= niveles:
                marca = "" if nodo.es_hoja else " …"
                lineas.append(f'    {ident}(["{nodo.clase} {nodo.confianza:.0%}<br/>n={nodo.n}{marca}"])')
                return
            pregunta = (f"{nodo.atributo} ≤ {_formatear_numero(nodo.umbral)}?" if nodo.umbral is not None
                        else f"{nodo.atributo}?")
            lineas.append(f'    {ident}{{"{pregunta}<br/>n={nodo.n}"}}')
            for rama, hijo in nodo.hijos.items():
                hijo_id = nuevo_id()
                etiqueta = ("sí" if rama == "<=" else "no") if nodo.umbral is not None else rama
                lineas.append(f'    {ident} -- "{etiqueta}" --> {hijo_id}')
                visitar(hijo, hijo_id)

        visitar(self.raiz, "n0")
        return "\n".join(lineas)

    # --- persistencia -----------------------------------------------------------
    def a_json(self) -> str:
        return json.dumps({
            "modelo": "ArbolDecision", "criterio": self.criterio, "profundidad_max": self.profundidad_max,
            "min_muestras_hoja": self.min_muestras_hoja, "ganancia_min": self.ganancia_min,
            "atributos": self.atributos, "tipos": self.tipos, "clases": self.clases,
            "raiz": self.raiz.a_dict(),
        }, ensure_ascii=False, indent=1)

    @classmethod
    def desde_json(cls, texto: str) -> "ArbolDecision":
        d = json.loads(texto)
        arbol = cls(d["criterio"], d["profundidad_max"], d["min_muestras_hoja"], d["ganancia_min"])
        arbol.atributos, arbol.tipos, arbol.clases = d["atributos"], d["tipos"], d["clases"]
        arbol.raiz = Nodo.desde_dict(d["raiz"])
        return arbol


# ---------------------------------------------------------------------------
# Líneas base
# ---------------------------------------------------------------------------

class ZeroR:
    """Predice siempre la clase mayoritaria."""

    def entrenar(self, X: Sequence[Ejemplo], y: Sequence[str], *_, **__) -> "ZeroR":
        conteos: Dict[str, int] = {}
        for c in y:
            conteos[c] = conteos.get(c, 0) + 1
        self.clase = _mayoritaria(conteos, sorted(conteos))
        return self

    def predecir(self, x: Ejemplo) -> str:
        return self.clase

    def predecir_lote(self, X: Sequence[Ejemplo]) -> List[str]:
        return [self.clase] * len(X)

    def __str__(self) -> str:
        return f"SIEMPRE {self.clase}"


class OneR:
    """1R de Holte: una regla por cada valor de UN solo atributo (el de menor error).
    Los atributos numéricos con más de 'max_valores' valores distintos se
    discretizan en intervalos de igual frecuencia."""

    def __init__(self, max_valores: int = 24, intervalos: int = 10):
        self.max_valores, self.intervalos = max_valores, intervalos

    def _cortes(self, valores: List[float]) -> List[float]:
        distintos = sorted(set(valores))
        if len(distintos) <= self.max_valores:
            return [(a + b) / 2 for a, b in zip(distintos, distintos[1:])]
        ordenados = sorted(valores)
        cortes = {ordenados[len(ordenados) * i // self.intervalos] for i in range(1, self.intervalos)}
        return sorted(cortes)

    def _clave(self, atributo: str, v: Valor):
        cortes = self.cortes.get(atributo)
        return bisect.bisect_left(cortes, v) if cortes is not None else v

    def entrenar(self, X: Sequence[Ejemplo], y: Sequence[str], atributos: Sequence[str],
                 tipos: Optional[Dict[str, str]] = None, **_) -> "OneR":
        tipos = tipos or inferir_tipos(X, atributos)
        self.cortes = {a: self._cortes([x[a] for x in X]) for a in atributos if tipos[a] == NUMERICO}
        clases = sorted(set(y))
        mejor = None
        for a in atributos:
            tabla: Dict[object, Dict[str, int]] = {}
            for x, c in zip(X, y):
                fila = tabla.setdefault(self._clave(a, x[a]), {})
                fila[c] = fila.get(c, 0) + 1
            regla = {v: _mayoritaria(cnt, clases) for v, cnt in tabla.items()}
            errores = sum(sum(cnt.values()) - cnt[regla[v]] for v, cnt in tabla.items())
            if mejor is None or errores < mejor[0]:
                mejor = (errores, a, regla)
        self.errores, self.atributo, self.regla = mejor
        self.por_defecto = ZeroR().entrenar(X, y).clase
        return self

    def predecir(self, x: Ejemplo) -> str:
        return self.regla.get(self._clave(self.atributo, x[self.atributo]), self.por_defecto)

    def predecir_lote(self, X: Sequence[Ejemplo]) -> List[str]:
        return [self.predecir(x) for x in X]

    def describir(self) -> List[str]:
        """Reglas legibles, agrupando intervalos contiguos con la misma clase."""
        cortes = self.cortes.get(self.atributo)
        if cortes is None:
            return [f"SI {self.atributo} = {v} ENTONCES {c}" for v, c in sorted(self.regla.items(), key=str)]
        lineas, inicio = [], None
        claves = sorted(self.regla)
        for i, k in enumerate(claves):
            if inicio is None:
                inicio = k
            if i + 1 < len(claves) and self.regla[claves[i + 1]] == self.regla[k]:
                continue
            inf = cortes[inicio - 1] if inicio > 0 else None
            sup = cortes[k] if k < len(cortes) else None
            if inf is not None and sup is not None:
                cond = f"{_formatear_numero(inf)} < {self.atributo} ≤ {_formatear_numero(sup)}"
            elif inf is not None:
                cond = f"{self.atributo} > {_formatear_numero(inf)}"
            else:
                cond = f"{self.atributo} ≤ {_formatear_numero(sup)}"
            lineas.append(f"SI {cond} ENTONCES {self.regla[k]}")
            inicio = None
        return lineas
