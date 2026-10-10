"""Pruebas avanzadas de los algoritmos de aprendizaje (Actividades 3 y 4): comparación con
oráculos de fuerza bruta, propiedades sobre datos aleatorios y un espía sobre el entrenamiento."""
import random
import unittest
from collections import defaultdict
from unittest import mock

from actividad4.no_supervisado import ATRIBUTOS, alinear, nombrar_grupos, ordenar_por_tamano, perfiles_estaciones
from aprendizaje.agrupamiento import (ENLACES, cortar, distancia2, estandarizar, indice_rand_ajustado, jerarquico,
                                      kmedias, silueta, silueta_por_muestra)
from aprendizaje.arbol import CATEGORICO, NUMERICO, ArbolDecision, OneR
from aprendizaje.datos import HORAS
from aprendizaje.evaluacion import (calcular_metricas, division_estratificada, exactitud, pliegues_estratificados,
                                    validar_profundidad)
from tests.oraculos import (alturas_por_definicion, ari_por_pares, ganancia, mejor_ganancia,
                            silueta_por_definicion)

TIPOS = {"entero": NUMERICO, "real": NUMERICO, "color": CATEGORICO, "forma": CATEGORICO}


def datos_aleatorios(rng, n, clases="abc"):
    """Ejemplos con dos atributos numéricos y dos categóricos, y etiquetas al azar."""
    X = [{"entero": rng.randint(0, 9), "real": round(rng.uniform(-5, 5), 1),
          "color": rng.choice(["rojo", "verde", "azul"]), "forma": rng.choice(["o", "x"])} for _ in range(n)]
    return X, [rng.choice(clases) for _ in range(n)]


def ejemplos_nuevos(rng, n):
    """Ejemplos que el árbol no vio: números fuera de rango y valores categóricos nuevos."""
    return [{"entero": rng.randint(-3, 12), "real": rng.uniform(-8, 8),
             "color": rng.choice(["rojo", "verde", "azul", "negro"]), "forma": rng.choice(["o", "x", "?"])}
            for _ in range(n)]


def sin_simplificar():
    """Desactiva la simplificación final (colapsa subárboles cuyas hojas predicen la misma clase)."""
    return mock.patch.object(ArbolDecision, "_simplificar", lambda self, nodo: None)


def nubes(rng, n, dimension=2):
    return [[rng.gauss(0, 3) for _ in range(dimension)] for _ in range(n)]


class TestArbolContraOraculo(unittest.TestCase):
    """El árbol elige la división que una búsqueda exhaustiva reconoce como la mejor."""

    def test_mejor_division_igual_a_la_busqueda_exhaustiva(self):
        rng = random.Random(3)
        comparadas = 0
        for caso in range(150):
            n, minimo = rng.randint(4, 40), rng.choice([1, 1, 2, 3])
            X, y = datos_aleatorios(rng, n, "ab" if caso % 2 else "abc")
            with sin_simplificar():
                arbol = ArbolDecision(profundidad_max=1, min_muestras_hoja=minimo).entrenar(X, y, list(TIPOS), TIPOS)
            raiz, mejor = arbol.raiz, mejor_ganancia(X, y, list(TIPOS), TIPOS, minimo)
            with self.subTest(caso=caso, n=n, minimo=minimo):
                if len(set(y)) == 1 or n < 2 * minimo:
                    self.assertTrue(raiz.es_hoja)
                    continue
                self.assertEqual(raiz.es_hoja, mejor <= arbol.ganancia_min)
                if raiz.es_hoja:
                    continue
                comparadas += 1
                self.assertAlmostEqual(raiz.ganancia, mejor, places=9)
                valores = sorted({x[raiz.atributo] for x in X}, key=str)
                if raiz.umbral is None:
                    grupos = [[i for i, x in enumerate(X) if x[raiz.atributo] == v] for v in valores]
                else:
                    valores.sort()
                    self.assertIn(raiz.umbral, [(a + b) / 2 for a, b in zip(valores, valores[1:])])
                    grupos = [[i for i, x in enumerate(X) if x[raiz.atributo] <= raiz.umbral],
                              [i for i, x in enumerate(X) if x[raiz.atributo] > raiz.umbral]]
                self.assertAlmostEqual(ganancia(y, grupos), raiz.ganancia, places=9)
        self.assertGreater(comparadas, 100)

    def test_hojas_impuras_solo_sin_division_util(self):
        """Sin la simplificación final, una hoja queda impura solo si ninguna división aporta ganancia."""
        rng = random.Random(4)
        impuras = 0
        for caso in range(100):
            X, y = datos_aleatorios(rng, rng.randint(5, 60))
            with sin_simplificar():
                arbol = ArbolDecision().entrenar(X, y, list(TIPOS), TIPOS)
            hojas = defaultdict(list)
            for i, x in enumerate(X):
                hojas[tuple(arbol.explicar(x).condiciones)].append(i)
            for indices in hojas.values():
                etiquetas = [y[i] for i in indices]
                if len(set(etiquetas)) > 1:
                    impuras += 1
                    with self.subTest(caso=caso, hoja=indices):
                        self.assertLessEqual(mejor_ganancia([X[i] for i in indices], etiquetas, list(TIPOS), TIPOS),
                                             arbol.ganancia_min)
        self.assertGreater(impuras, 0)

    def test_simplificar_no_cambia_ninguna_prediccion(self):
        rng = random.Random(5)
        colapsos = 0
        for caso in range(100):
            X, y = datos_aleatorios(rng, rng.randint(5, 60))
            simplificado = ArbolDecision().entrenar(X, y, list(TIPOS), TIPOS)
            with sin_simplificar():
                completo = ArbolDecision().entrenar(X, y, list(TIPOS), TIPOS)
            todos = X + ejemplos_nuevos(rng, 40)
            with self.subTest(caso=caso):
                self.assertEqual(simplificado.predecir_lote(todos), completo.predecir_lote(todos))
                self.assertLessEqual(simplificado.contar()[0], completo.contar()[0])
            colapsos += simplificado.contar()[0] < completo.contar()[0]
        self.assertGreater(colapsos, 0)

    def test_ajuste_perfecto_con_un_atributo_identificador(self):
        """Con un atributo numérico distinto en cada ejemplo, toda hoja impura se puede dividir."""
        rng = random.Random(6)
        for caso in range(50):
            X, y = datos_aleatorios(rng, rng.randint(5, 60))
            identificadores = rng.sample(range(len(X)), len(X))
            X = [dict(x, ident=i) for x, i in zip(X, identificadores)]
            with self.subTest(caso=caso):
                arbol = ArbolDecision().entrenar(X, y, list(TIPOS) + ["ident"])
                self.assertEqual(arbol.predecir_lote(X), y)

    def test_xor_no_tiene_ganancia_en_la_raiz(self):
        """Límite conocido de la elección voraz: en XOR ningún atributo aporta ganancia por sí solo."""
        X = [{"a": a, "b": b} for a in (0, 1) for b in (0, 1) for _ in range(3)]
        y = ["si" if x["a"] != x["b"] else "no" for x in X]
        self.assertTrue(ArbolDecision().entrenar(X, y, ["a", "b"]).raiz.es_hoja)
        self.assertAlmostEqual(mejor_ganancia(X, y, ["a", "b"], {"a": NUMERICO, "b": NUMERICO}), 0.0)


class TestArbolPropiedades(unittest.TestCase):
    """Propiedades que se cumplen con cualquier conjunto de datos."""

    def setUp(self):
        self.rng = random.Random(7)

    def arboles(self, cantidad):
        for caso in range(cantidad):
            X, y = datos_aleatorios(self.rng, self.rng.randint(5, 80))
            minimo = self.rng.choice([1, 2, 4])
            yield caso, X, y, ArbolDecision(min_muestras_hoja=minimo).entrenar(X, y, list(TIPOS), TIPOS)

    def test_reglas_particionan_los_datos_con_soporte_y_confianza_exactos(self):
        for caso, X, y, arbol in self.arboles(60):
            reglas = arbol.extraer_reglas()
            with self.subTest(caso=caso):
                for x in X:
                    self.assertEqual(sum(r.cubre(x) for r in reglas), 1)
                for r in reglas:
                    cubiertas = [c for x, c in zip(X, y) if r.cubre(x)]
                    self.assertEqual(r.soporte, len(cubiertas))
                    self.assertAlmostEqual(r.confianza, cubiertas.count(r.clase) / len(cubiertas))

    def test_prediccion_truncada_igual_a_un_arbol_menos_profundo(self):
        for caso in range(40):
            X, y = datos_aleatorios(self.rng, self.rng.randint(10, 80))
            minimo = self.rng.choice([1, 2, 4])
            profundo = ArbolDecision(profundidad_max=8, min_muestras_hoja=minimo).entrenar(X, y, list(TIPOS), TIPOS)
            todos = X + ejemplos_nuevos(self.rng, 40)
            for d in range(8):
                corto = ArbolDecision(profundidad_max=d, min_muestras_hoja=minimo).entrenar(X, y, list(TIPOS), TIPOS)
                with self.subTest(caso=caso, profundidad=d):
                    self.assertEqual(profundo.predecir_lote(todos, d), corto.predecir_lote(todos))

    def test_json_ida_y_vuelta(self):
        for caso, X, y, arbol in self.arboles(40):
            copia = ArbolDecision.desde_json(arbol.a_json())
            todos = X + ejemplos_nuevos(self.rng, 20)
            with self.subTest(caso=caso):
                self.assertEqual(copia.predecir_lote(todos), arbol.predecir_lote(todos))
                self.assertEqual([str(r) for r in copia.extraer_reglas()], [str(r) for r in arbol.extraer_reglas()])
                self.assertEqual(copia.a_texto(), arbol.a_texto())
                self.assertEqual(copia.a_json(), arbol.a_json())

    def test_importancia_no_negativa_y_suma_uno(self):
        for caso, X, y, arbol in self.arboles(40):
            importancia = arbol.importancia()
            with self.subTest(caso=caso):
                self.assertEqual(set(importancia), set(TIPOS))
                self.assertTrue(all(v >= 0 for v in importancia.values()))
                self.assertAlmostEqual(sum(importancia.values()), 0.0 if arbol.raiz.es_hoja else 1.0)


class TestOneR(unittest.TestCase):
    def test_discretiza_en_intervalos_de_igual_frecuencia(self):
        X = [{"x": v} for v in range(100)]
        oner = OneR().entrenar(X, ["a" if v < 50 else "b" for v in range(100)], ["x"])
        self.assertEqual(oner.cortes["x"], list(range(10, 100, 10)))
        self.assertEqual(oner.errores, 1)        # el intervalo (40, 50] incluye el 50, que es "b"
        self.assertEqual(oner.describir(), ["SI x ≤ 50 ENTONCES a", "SI x > 50 ENTONCES b"])
        oner = OneR().entrenar(X, ["b" if 30 <= v < 70 else "a" for v in range(100)], ["x"])
        self.assertEqual(oner.errores, 2)
        self.assertEqual(oner.describir(),
                         ["SI x ≤ 30 ENTONCES a", "SI 30 < x ≤ 70 ENTONCES b", "SI x > 70 ENTONCES a"])

    def test_valor_no_visto_usa_la_clase_por_defecto(self):
        X = [{"color": c} for c in ("rojo", "rojo", "azul", "azul", "azul")]
        oner = OneR().entrenar(X, ["no", "no", "si", "si", "si"], ["color"])
        self.assertEqual(oner.predecir({"color": "verde"}), "si")     # la clase mayoritaria (ZeroR)


class TestEvaluacionPropiedades(unittest.TestCase):
    def test_metricas_coherentes_en_vectores_aleatorios(self):
        rng = random.Random(8)
        clases = ["a", "b", "c"]
        for caso in range(200):
            n = rng.randint(1, 50)
            reales = [rng.choice(clases) for _ in range(n)]
            predichas = list(reales) if caso % 10 == 0 else [rng.choice(clases) for _ in range(n)]
            m = calcular_metricas(reales, predichas, clases)
            with self.subTest(caso=caso):
                self.assertEqual([sum(fila) for fila in m.matriz], [reales.count(c) for c in clases])
                self.assertEqual([sum(col) for col in zip(*m.matriz)], [predichas.count(c) for c in clases])
                self.assertAlmostEqual(m.exactitud, sum(m.matriz[i][i] for i in range(3)) / n)
                self.assertAlmostEqual(m.exactitud, exactitud(reales, predichas))
                self.assertAlmostEqual(m.f1_macro, sum(v["f1"] for v in m.por_clase.values()) / 3)
                for v in m.por_clase.values():
                    self.assertTrue(all(0 <= v[k] <= 1 for k in ("precision", "recall", "f1")))
                if predichas == reales:
                    self.assertTrue(all(m.por_clase[c]["f1"] == 1.0 for c in set(reales)))

    def test_clase_nunca_predicha_no_divide_por_cero(self):
        m = calcular_metricas(["a", "a", "b"], ["a", "a", "a"], ["a", "b"])
        self.assertEqual(m.por_clase["b"], {"precision": 0.0, "recall": 0.0, "f1": 0.0, "soporte": 1})
        self.assertAlmostEqual(m.por_clase["a"]["precision"], 2 / 3)

    def test_division_estratificada_en_datos_aleatorios(self):
        rng = random.Random(9)
        for caso in range(100):
            y = [rng.choice("aaabbc") for _ in range(rng.randint(5, 150))]
            proporcion, semilla = rng.choice([0.2, 0.3, 0.5]), rng.randint(0, 99)
            entrenamiento, prueba = division_estratificada(y, proporcion, semilla)
            with self.subTest(caso=caso):
                self.assertEqual(sorted(entrenamiento + prueba), list(range(len(y))))
                for c in set(y):
                    self.assertEqual(sum(y[i] == c for i in prueba), round(y.count(c) * proporcion))
                self.assertEqual(division_estratificada(y, proporcion, semilla), (entrenamiento, prueba))

    def test_pliegues_equilibrados_por_clase(self):
        rng = random.Random(10)
        for caso in range(100):
            y = [rng.choice("aaabbc") for _ in range(rng.randint(5, 150))]
            k = rng.randint(2, 6)
            pliegues = pliegues_estratificados(y, k, semilla=caso)
            with self.subTest(caso=caso, k=k):
                self.assertEqual(sorted(i for p in pliegues for i in p), list(range(len(y))))
                for c in set(y):
                    por_pliegue = [sum(y[i] == c for i in p) for p in pliegues]
                    self.assertLessEqual(max(por_pliegue) - min(por_pliegue), 1)

    def test_validacion_cruzada_sin_fuga_de_datos(self):
        """Un espía registra con qué ejemplos se entrena cada pliegue: nunca con los que se validan."""
        X = [{"x": i % 7, "c": "pq"[i % 2], "_id": i} for i in range(90)]
        y = ["a" if i % 7 < 3 else "b" for i in range(90)]
        entrenar, entrenados = ArbolDecision.entrenar, []

        def espia(arbol, X_ent, *args, **kwargs):
            entrenados.append({x["_id"] for x in X_ent})
            return entrenar(arbol, X_ent, *args, **kwargs)

        with mock.patch.object(ArbolDecision, "entrenar", espia):
            validar_profundidad(X, y, ["x", "c"], range(1, 4), k=3, semilla=1)
        validados = [set(range(90)) - ids for ids in entrenados]
        self.assertEqual(validados, [set(p) for p in pliegues_estratificados(y, 3, semilla=1)])
        self.assertEqual(sorted(i for v in validados for i in v), list(range(90)))   # disjuntos y completos


class TestAgrupamientoContraOraculo(unittest.TestCase):
    def test_jerarquico_igual_a_la_definicion_de_cada_enlace(self):
        """La actualización de Lance-Williams da en cada paso la misma altura que recalcular desde cero."""
        rng = random.Random(11)
        for caso in range(25):
            X = nubes(rng, rng.randint(2, 14), dimension=3)
            for enlace in ENLACES:
                fusiones = jerarquico(X, enlace)
                with self.subTest(caso=caso, enlace=enlace):
                    esperadas = alturas_por_definicion(X, enlace)
                    self.assertEqual(len(fusiones), len(esperadas))
                    for (_, _, altura, _), esperada in zip(fusiones, esperadas):
                        self.assertAlmostEqual(altura, esperada, places=9)
                    tamano = {i: 1 for i in range(len(X))}
                    for paso, (a, b, _, t) in enumerate(fusiones):   # el grupo nuevo recibe el id n + paso
                        self.assertEqual(t, tamano.pop(a) + tamano.pop(b))
                        tamano[len(X) + paso] = t

    def test_cortes_anidados(self):
        rng = random.Random(12)
        for caso in range(25):
            X = nubes(rng, rng.randint(2, 20))
            n, fusiones = len(X), jerarquico(X, rng.choice(ENLACES))
            for k in range(1, n + 1):
                etiquetas = cortar(fusiones, n, k)
                with self.subTest(caso=caso, k=k):
                    self.assertEqual(list(dict.fromkeys(etiquetas)), list(range(k)))   # k grupos, por aparición
                    if k > 1:   # cada grupo con k cae entero dentro de un grupo con k - 1
                        self.assertEqual(len(set(zip(etiquetas, cortar(fusiones, n, k - 1)))), k)

    def test_silueta_igual_a_la_definicion(self):
        rng = random.Random(13)
        for caso in range(50):
            X = [[rng.random(), rng.random()] for _ in range(rng.randint(3, 25))]
            etiquetas = [rng.randint(0, 2) for _ in X]
            if len(set(etiquetas)) < 2:
                continue
            with self.subTest(caso=caso):
                for obtenida, esperada in zip(silueta_por_muestra(X, etiquetas), silueta_por_definicion(X, etiquetas)):
                    self.assertAlmostEqual(obtenida, esperada, places=9)
        self.assertEqual(silueta_por_muestra([[0, 0], [1, 1], [5, 5]], [0, 0, 1])[2], 0.0)   # grupo de un punto
        self.assertEqual(silueta([[1, 1]] * 4, [0, 0, 1, 1]), 0.0)                          # puntos idénticos
        with self.assertRaises(ValueError):
            silueta([[0, 0], [1, 1]], [0, 0])

    def test_ari_igual_al_conteo_de_pares(self):
        rng = random.Random(14)
        letras = {0: "w", 1: "x", 2: "y", 3: "z"}
        for caso in range(300):
            n = rng.randint(1, 30)
            a, b = [rng.randint(0, 3) for _ in range(n)], [rng.randint(0, 4) for _ in range(n)]
            with self.subTest(caso=caso, a=a, b=b):
                ari = indice_rand_ajustado(a, b)
                self.assertAlmostEqual(ari, ari_por_pares(a, b), places=9)
                self.assertAlmostEqual(ari, indice_rand_ajustado(b, a), places=12)
                self.assertAlmostEqual(ari, indice_rand_ajustado([letras[e] for e in a], b), places=12)

    def test_ari_de_particiones_al_azar_es_cercano_a_cero(self):
        rng = random.Random(15)
        valores = [indice_rand_ajustado([rng.randint(0, 2) for _ in range(60)], [rng.randint(0, 2) for _ in range(60)])
                   for _ in range(400)]
        self.assertLess(abs(sum(valores) / len(valores)), 0.02)


class TestKMedias(unittest.TestCase):
    def test_resultado_es_un_punto_fijo_de_lloyd(self):
        """Cada centroide es la media de su grupo y cada punto está más cerca de su centroide que de los demás."""
        rng = random.Random(16)
        for caso in range(30):
            X, k = nubes(rng, rng.randint(6, 40)), rng.randint(1, 5)
            r = kmedias(X, k, semilla=caso)
            with self.subTest(caso=caso, k=k):
                self.assertEqual(list(dict.fromkeys(r.etiquetas)), list(range(k)))
                for g, centro in enumerate(r.centroides):
                    miembros = [x for x, e in zip(X, r.etiquetas) if e == g]
                    for d in range(2):
                        self.assertAlmostEqual(centro[d], sum(x[d] for x in miembros) / len(miembros))
                for x, e in zip(X, r.etiquetas):
                    self.assertLessEqual(distancia2(x, r.centroides[e]),
                                         min(distancia2(x, c) for c in r.centroides) + 1e-9)
                self.assertAlmostEqual(r.sse, sum(distancia2(x, r.centroides[e]) for x, e in zip(X, r.etiquetas)))

    def test_invariante_a_traslaciones(self):
        rng = random.Random(17)
        for caso in range(20):
            X, k = nubes(rng, rng.randint(6, 40)), rng.randint(2, 5)
            trasladados = [[a + 1000.0, b - 250.0] for a, b in X]
            with self.subTest(caso=caso, k=k):
                self.assertAlmostEqual(indice_rand_ajustado(kmedias(X, k, semilla=caso).etiquetas,
                                                            kmedias(trasladados, k, semilla=caso).etiquetas), 1.0)

    def test_mas_reinicios_nunca_empeoran_el_sse(self):
        """El primer reinicio de n_init=10 es el de n_init=1 (misma semilla): el mejor de 10 no puede ser peor."""
        rng = random.Random(18)
        for caso in range(30):
            X, k = nubes(rng, rng.randint(5, 40)), rng.randint(1, 5)
            with self.subTest(caso=caso, k=k):
                self.assertLessEqual(kmedias(X, k, semilla=caso, n_init=10).sse,
                                     kmedias(X, k, semilla=caso, n_init=1).sse + 1e-9)

    def test_estandarizar_columna_constante(self):
        Z, medias, desv = estandarizar([[1, 5], [2, 5], [3, 5]])
        self.assertEqual([z[1] for z in Z], [0.0, 0.0, 0.0])
        self.assertEqual((medias[1], desv[1]), (5.0, 1.0))

    def test_alinear_y_ordenar_conservan_la_particion(self):
        rng = random.Random(19)
        for caso in range(100):
            n, k = rng.randint(2, 30), rng.randint(1, 5)
            a, b = [rng.randrange(k) for _ in range(n)], [rng.randrange(k) for _ in range(n)]
            ordenadas = ordenar_por_tamano(a)
            with self.subTest(caso=caso):
                self.assertAlmostEqual(indice_rand_ajustado(ordenadas, a), 1.0)
                tamanos = [ordenadas.count(g) for g in range(max(ordenadas) + 1)]
                self.assertEqual(tamanos, sorted(tamanos, reverse=True))
                self.assertAlmostEqual(indice_rand_ajustado(alinear(a, b), b), 1.0)
                permutacion = rng.sample(range(k), k)
                self.assertEqual(alinear(a, [permutacion[e] for e in a]), a)


class TestPerfilesYNombres(unittest.TestCase):
    @staticmethod
    def fila(fecha, tipo_dia, hora, entradas, salidas):
        return {"fecha": fecha, "tipo_dia": tipo_dia, "hora": hora, "estacion": "A",
                "entradas": entradas, "salidas": salidas}

    def test_atributos_calculados_a_mano(self):
        filas = [self.fila(fecha, "habil", h, e, s) for fecha in ("2026-03-02", "2026-03-03")
                 for h, e, s in [(6, 60, 0), (7, 0, 10), (12, 20, 10), (17, 20, 0), (18, 0, 30)]]
        filas += [self.fila("2026-03-07", "sabado", 12, 30, 20), self.fila("2026-03-08", "domingo_festivo", 12, 70, 40)]
        (perfil,) = perfiles_estaciones(filas)
        # Por día hábil: 100 entradas (60 a las 6, 20 a las 17) y 50 salidas (10 a las 7, 30 a las 18);
        # fin de semana: 100 entradas en 2 días = 50 por día
        esperados = {"log_volumen": 2.0, "pico_am_entradas": 0.6, "pico_pm_entradas": 0.2,
                     "pico_am_salidas": 0.2, "pico_pm_salidas": 0.6, "ratio_fin_de_semana": 0.5}
        for atributo, valor in esperados.items():
            self.assertAlmostEqual(perfil.atributos[atributo], valor, msg=atributo)
        self.assertEqual(perfil.vector(), [perfil.atributos[a] for a in ATRIBUTOS])
        self.assertAlmostEqual(perfil.entradas_dia, 100.0)
        self.assertAlmostEqual(perfil.entradas_hora[HORAS.index(6)], 60.0)
        self.assertAlmostEqual(sum(perfil.salidas_hora), 100.0)

    def test_sin_fin_de_semana_es_un_error(self):
        with self.assertRaises(ValueError):
            perfiles_estaciones([self.fila("2026-03-02", "habil", 6, 10, 10)])

    def test_reglas_para_nombrar_grupos(self):
        residencial = [4.0, 0.4, 0.1, 0.1, 0.3, 0.3]    # índice residencial (0.4 − 0.1) + (0.3 − 0.1) = 0.5
        empleo = [4.0, 0.1, 0.5, 0.5, 0.1, 0.3]         # índice −0.8
        mixta = [4.0, 0.3, 0.3, 0.3, 0.3, 0.3]          # índice 0
        z, z_ocio, z_grande = [0.0] * 6, [0.0] * 5 + [1.0], [1.5] + [0.0] * 5
        nombres = nombrar_grupos([residencial, empleo, mixta, residencial, mixta], [z, z, z, z_ocio, z_grande])
        self.assertEqual([i for _, i in nombres],
                         ["residencial", "empleo", "mixta", "ocio_fin_de_semana", "mixta_alta_demanda"])
        self.assertEqual(nombres[4][0], "Mixta - alta demanda")
        self.assertEqual([i for _, i in nombrar_grupos([empleo] * 3, [z] * 3)], ["empleo_1", "empleo_2", "empleo_3"])


if __name__ == "__main__":
    unittest.main()
