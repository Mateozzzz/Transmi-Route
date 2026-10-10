"""Oráculos de prueba: implementaciones de referencia simples, lentas e independientes de
los algoritmos que se prueban. Las pruebas avanzadas comparan contra ellas la búsqueda,
el motor de inferencia, el árbol de decisión y el agrupamiento.

Este archivo no empieza por test_, así que unittest no lo recorre como pruebas."""
import heapq
import itertools
import math
from collections import Counter, defaultdict, deque

from aprendizaje.arbol import CATEGORICO
from sistema.busqueda import A_PIE, Estado, ProblemaRuta


# ---------------------------------------------------------------------------
# Búsqueda (Actividad 2): usan solo los sucesores del problema, no los algoritmos
# ---------------------------------------------------------------------------

def dijkstra_completo(red, origen, criterio="tiempo"):
    """Costo mínimo desde 'origen' hasta CADA estación: Dijkstra sobre todo el espacio de
    estados, sin prueba de meta."""
    p = ProblemaRuta(red, origen, origen, criterio)
    g = {p.inicial: 0.0}
    frontera = [(0.0, 0, p.inicial)]
    desempate = itertools.count(1)
    mejor = {}
    while frontera:
        costo, _, s = heapq.heappop(frontera)
        if costo > g[s]:
            continue
        mejor.setdefault(s.estacion, costo)
        for _, s2, c in p.sucesores(s):
            if costo + c < g.get(s2, math.inf):
                g[s2] = costo + c
                heapq.heappush(frontera, (g[s2], next(desempate), s2))
    return mejor


def aristas_del_espacio(red, criterio="tiempo"):
    """Aristas (estado, sucesor, costo) alcanzables desde el estado inicial de cada estación."""
    p = ProblemaRuta(red, red.estaciones[0], red.estaciones[0], criterio)
    pendientes = deque(Estado(e, None) for e in red.estaciones)
    vistos = set(pendientes)
    aristas = set()
    while pendientes:
        s = pendientes.popleft()
        for _, s2, costo in p.sucesores(s):
            aristas.add((s, s2, costo))
            if s2 not in vistos:
                vistos.add(s2)
                pendientes.append(s2)
    return aristas


def menos_acciones(red, origen, destino):
    """Número mínimo de acciones (abordar, viajar, transbordo, caminar) entre dos estaciones."""
    p = ProblemaRuta(red, origen, destino)
    if p.es_meta(p.inicial):
        return 0
    nivel = {p.inicial: 0}
    pendientes = deque([p.inicial])
    while pendientes:
        s = pendientes.popleft()
        for _, s2, _ in p.sucesores(s):
            if s2 not in nivel:
                nivel[s2] = nivel[s] + 1
                if p.es_meta(s2):
                    return nivel[s2]
                pendientes.append(s2)
    return None


def transbordos_y_minutos(red, origen, destino):
    """(transbordos, minutos) mínimos en orden lexicográfico: primero los menos transbordos y,
    entre ellos, el menor tiempo. Abordar después de caminar cuenta como transbordo."""
    p = ProblemaRuta(red, origen, destino)
    g = {p.inicial: (0, 0.0)}
    frontera = [((0, 0.0), 0, p.inicial)]
    desempate = itertools.count(1)
    while frontera:
        costo, _, s = heapq.heappop(frontera)
        if costo > g[s]:
            continue
        if p.es_meta(s):
            return costo
        for paso, s2, _ in p.sucesores(s):
            es_transbordo = paso.accion == "transbordo" or (paso.accion == "abordar" and s.troncal == A_PIE)
            nuevo = (costo[0] + es_transbordo, costo[1] + paso.minutos)
            if nuevo < g.get(s2, (math.inf, math.inf)):
                g[s2] = nuevo
                heapq.heappush(frontera, (nuevo, next(desempate), s2))
    return None


# ---------------------------------------------------------------------------
# Inferencia (Actividad 2)
# ---------------------------------------------------------------------------

def cierre_transitivo(nodos, aristas):
    """Pares (a, b) tales que b se alcanza desde a siguiendo al menos una arista."""
    vecinos = {n: [] for n in nodos}
    for a, b in aristas:
        vecinos[a].append(b)
    pares = set()
    for inicio in nodos:
        vistos, pendientes = set(), deque(vecinos[inicio])
        while pendientes:
            n = pendientes.popleft()
            if n not in vistos:
                vistos.add(n)
                pendientes.extend(vecinos[n])
        pares |= {(inicio, n) for n in vistos}
    return pares


# ---------------------------------------------------------------------------
# Árbol de decisión (Actividad 3)
# ---------------------------------------------------------------------------

def _entropia(etiquetas):
    n = len(etiquetas)
    return -sum(c / n * math.log2(c / n) for c in Counter(etiquetas).values())


def ganancia(y, grupos):
    """Ganancia de información de partir las etiquetas y en los grupos de índices dados."""
    return _entropia(y) - sum(len(g) / len(y) * _entropia([y[i] for i in g]) for g in grupos)


def divisiones(X, atributo, tipo):
    """Todas las divisiones de X por un atributo, como (umbral, grupos de índices).
    Categórico: un grupo por valor y umbral None. Numérico: cada punto medio entre dos
    valores consecutivos, con los grupos ≤ umbral y > umbral."""
    if tipo == CATEGORICO:
        grupos = defaultdict(list)
        for i, x in enumerate(X):
            grupos[x[atributo]].append(i)
        return [(None, list(grupos.values()))] if len(grupos) > 1 else []
    valores = sorted({x[atributo] for x in X})
    return [((a + b) / 2, [[i for i, x in enumerate(X) if x[atributo] <= (a + b) / 2],
                           [i for i, x in enumerate(X) if x[atributo] > (a + b) / 2]])
            for a, b in zip(valores, valores[1:])]


def mejor_ganancia(X, y, atributos, tipos, minimo=1):
    """Mayor ganancia entre todas las divisiones con al menos 'minimo' ejemplos por rama (0 si no hay)."""
    return max((ganancia(y, grupos) for a in atributos for _, grupos in divisiones(X, a, tipos[a])
                if min(len(g) for g in grupos) >= minimo), default=0.0)


# ---------------------------------------------------------------------------
# Agrupamiento (Actividad 4)
# ---------------------------------------------------------------------------

def distancia_entre_grupos(X, A, B, enlace):
    """Distancia entre los grupos de índices A y B según la definición de cada enlace."""
    pares = [math.dist(X[i], X[j]) for i in A for j in B]
    if enlace == "simple":
        return min(pares)
    if enlace == "completo":
        return max(pares)
    if enlace == "promedio":
        return sum(pares) / len(pares)
    centro_a = [sum(X[i][d] for i in A) / len(A) for d in range(len(X[0]))]
    centro_b = [sum(X[i][d] for i in B) / len(B) for d in range(len(X[0]))]
    return math.sqrt(2 * len(A) * len(B) / (len(A) + len(B))) * math.dist(centro_a, centro_b)


def alturas_por_definicion(X, enlace):
    """Alturas de fusión del agrupamiento aglomerativo, recalculando en cada paso la
    distancia entre todos los grupos con su definición (sin la fórmula de Lance-Williams)."""
    grupos = [[i] for i in range(len(X))]
    alturas = []
    while len(grupos) > 1:
        d, a, b = min((distancia_entre_grupos(X, grupos[a], grupos[b], enlace), a, b)
                      for a, b in itertools.combinations(range(len(grupos)), 2))
        alturas.append(d)
        grupos[a] += grupos.pop(b)
    return alturas


def silueta_por_definicion(X, etiquetas):
    """s(i) = (b − a) / max(a, b) punto por punto; 0 si el grupo de i tiene un solo punto."""
    valores = []
    for i, x in enumerate(X):
        propios = [math.dist(x, X[j]) for j, e in enumerate(etiquetas) if e == etiquetas[i] and j != i]
        if not propios:
            valores.append(0.0)
            continue
        a = sum(propios) / len(propios)
        b = min(sum(math.dist(x, X[j]) for j, e in enumerate(etiquetas) if e == g) / etiquetas.count(g)
                for g in set(etiquetas) - {etiquetas[i]})
        valores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return valores


def ari_por_pares(a, b):
    """Índice de Rand ajustado contando pares de elementos juntos o separados en cada partición."""
    juntos = solo_a = solo_b = separados = 0
    for i, j in itertools.combinations(range(len(a)), 2):
        en_a, en_b = a[i] == a[j], b[i] == b[j]
        if en_a and en_b:
            juntos += 1
        elif en_a:
            solo_a += 1
        elif en_b:
            solo_b += 1
        else:
            separados += 1
    if solo_a == 0 and solo_b == 0:
        return 1.0
    return (2 * (juntos * separados - solo_a * solo_b)
            / ((juntos + solo_a) * (solo_a + separados) + (juntos + solo_b) * (solo_b + separados)))
