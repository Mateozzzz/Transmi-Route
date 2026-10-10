"""Pruebas del árbol de decisión, las reglas, las líneas base y las métricas."""
import unittest

from actividad3.supervisado import ATRIBUTOS, CLASES, ejemplo, franja, nivel_demanda, preparar
from aprendizaje.arbol import ArbolDecision, OneR, ZeroR, entropia
from aprendizaje.datos import atributos_estaciones, generar_dataset, unir_atributos
from aprendizaje.evaluacion import (calcular_metricas, division_estratificada, exactitud,
                                    pliegues_estratificados, validar_profundidad)
from sistema.red import RedTransporte

# Ejemplo clásico "jugar tenis" (Quinlan, 1986), usado en los textos de árboles de decisión
_TENIS = """
soleado caliente alta debil no
soleado caliente alta fuerte no
nublado caliente alta debil si
lluvioso templada alta debil si
lluvioso fresca normal debil si
lluvioso fresca normal fuerte no
nublado fresca normal fuerte si
soleado templada alta debil no
soleado fresca normal debil si
lluvioso templada normal debil si
soleado templada normal fuerte si
nublado templada alta fuerte si
nublado caliente normal debil si
lluvioso templada alta fuerte no
"""
ATR_TENIS = ["cielo", "temperatura", "humedad", "viento"]
X_TENIS = [dict(zip(ATR_TENIS, linea.split()[:4])) for linea in _TENIS.strip().splitlines()]
Y_TENIS = [linea.split()[4] for linea in _TENIS.strip().splitlines()]

# ID3 y C4.5 eligen raíces distintas: "a" (4 ramas) tiene más ganancia, pero "b" (2 ramas)
# tiene mayor razón de ganancia. "c" aporta poca ganancia y baja el promedio, así que "a" y
# "b" pasan el filtro de C4.5 (solo compite quien tiene ganancia ≥ promedio).
_RAZON = """
g1 b1 c1 si
g1 b1 c1 si
g1 b1 c1 si
g1 b1 c1 si
g3 b1 c1 si
g3 b1 c2 si
g3 b1 c2 si
g4 b2 c2 si
g3 b1 c1 no
g4 b2 c1 no
g4 b2 c1 no
g4 b2 c2 no
g2 b2 c2 no
g2 b2 c2 no
g2 b2 c2 no
g2 b2 c2 no
"""
X_RAZON = [dict(zip("abc", linea.split()[:3])) for linea in _RAZON.strip().splitlines()]
Y_RAZON = [linea.split()[3] for linea in _RAZON.strip().splitlines()]


class TestEntropiaEID3(unittest.TestCase):
    def test_entropia(self):
        self.assertAlmostEqual(entropia([9, 5]), 0.940, places=3)
        self.assertAlmostEqual(entropia([7, 7]), 1.0)
        self.assertEqual(entropia([4, 0]), 0.0)

    def test_id3_elige_cielo_como_raiz(self):
        arbol = ArbolDecision().entrenar(X_TENIS, Y_TENIS, ATR_TENIS)
        self.assertEqual(arbol.raiz.atributo, "cielo")
        self.assertAlmostEqual(arbol.raiz.ganancia, 0.2467, places=3)
        self.assertEqual(arbol.raiz.hijos["nublado"].clase, "si")
        self.assertTrue(arbol.raiz.hijos["nublado"].es_hoja)
        self.assertEqual(arbol.raiz.hijos["soleado"].atributo, "humedad")
        self.assertEqual(arbol.raiz.hijos["lluvioso"].atributo, "viento")
        self.assertEqual(arbol.predecir_lote(X_TENIS), Y_TENIS)
        self.assertEqual(arbol.contar()[1], 5)   # 5 hojas = 5 reglas

    def test_razon_de_ganancia(self):
        arbol = ArbolDecision(criterio="razon").entrenar(X_TENIS, Y_TENIS, ATR_TENIS)
        self.assertEqual(arbol.predecir_lote(X_TENIS), Y_TENIS)
        id3 = ArbolDecision().entrenar(X_RAZON, Y_RAZON, ["a", "b", "c"]).raiz
        c45 = ArbolDecision(criterio="razon").entrenar(X_RAZON, Y_RAZON, ["a", "b", "c"]).raiz
        self.assertEqual((id3.atributo, round(id3.ganancia, 4)), ("a", 0.5944))   # razón 0.5944 / 2 = 0.297
        self.assertEqual((c45.atributo, round(c45.ganancia, 4)), ("b", 0.4564))   # razón 0.4564 / 1

    def test_criterio_invalido(self):
        with self.assertRaises(ValueError):
            ArbolDecision(criterio="gini")

    def test_umbral_numerico(self):
        X = [{"x": v} for v in (1, 2, 3, 10, 11, 12)]
        y = ["a", "a", "a", "b", "b", "b"]
        arbol = ArbolDecision().entrenar(X, y, ["x"])
        self.assertEqual(arbol.raiz.umbral, 6.5)
        self.assertEqual(arbol.predecir({"x": 5}), "a")
        self.assertEqual(arbol.predecir({"x": 8}), "b")

    def test_nodo_puro_es_hoja(self):
        arbol = ArbolDecision().entrenar(X_TENIS[:2], Y_TENIS[:2], ATR_TENIS)
        self.assertTrue(arbol.raiz.es_hoja)
        self.assertEqual(arbol.predecir(X_TENIS[5]), "no")

    def test_valor_no_visto_usa_la_clase_del_nodo(self):
        arbol = ArbolDecision().entrenar(X_TENIS, Y_TENIS, ATR_TENIS)
        self.assertEqual(arbol.predecir({"cielo": "nevando", "humedad": "alta", "viento": "debil"}),
                         arbol.raiz.clase)


class TestReglas(unittest.TestCase):
    def test_reglas_excluyentes_y_exhaustivas(self):
        arbol = ArbolDecision().entrenar(X_TENIS, Y_TENIS, ATR_TENIS)
        reglas = arbol.extraer_reglas()
        self.assertEqual(len(reglas), 5)
        for x in X_TENIS:
            cubren = [r for r in reglas if r.cubre(x)]
            self.assertEqual(len(cubren), 1)
            self.assertEqual(cubren[0].clase, arbol.predecir(x))
        self.assertEqual(sum(r.soporte for r in reglas), len(X_TENIS))

    def test_explicar_y_texto_de_intervalos(self):
        X = [{"h": h} for h in range(10)]
        y = ["b", "b", "a", "a", "a", "b", "b", "b", "b", "b"]
        arbol = ArbolDecision().entrenar(X, y, ["h"])
        regla = arbol.explicar({"h": 3})
        self.assertEqual(regla.clase, "a")
        self.assertEqual(regla.texto_condiciones(), "1.5 < h ≤ 4.5")

    def test_oner_y_zeror(self):
        oner = OneR().entrenar(X_TENIS, Y_TENIS, ATR_TENIS)
        self.assertEqual(oner.atributo, "cielo")
        self.assertEqual(oner.errores, 4)
        self.assertEqual(ZeroR().entrenar(X_TENIS, Y_TENIS).clase, "si")


class TestMetricasYParticiones(unittest.TestCase):
    def test_metricas_a_mano(self):
        reales = ["a", "a", "b", "b", "b", "c"]
        predichas = ["a", "b", "b", "b", "c", "c"]
        m = calcular_metricas(reales, predichas, ["a", "b", "c"])
        self.assertEqual(m.matriz, [[1, 1, 0], [0, 2, 1], [0, 0, 1]])
        self.assertAlmostEqual(m.exactitud, 4 / 6)
        self.assertAlmostEqual(m.por_clase["a"]["precision"], 1.0)
        self.assertAlmostEqual(m.por_clase["a"]["recall"], 0.5)
        self.assertAlmostEqual(m.por_clase["b"]["f1"], 2 / 3)
        self.assertAlmostEqual(m.por_clase["c"]["precision"], 0.5)
        self.assertAlmostEqual(m.por_clase["c"]["recall"], 1.0)

    def test_division_estratificada(self):
        y = ["a"] * 70 + ["b"] * 30
        ent, pru = division_estratificada(y, 0.3, semilla=1)
        self.assertEqual(sorted(ent + pru), list(range(100)))
        self.assertEqual(sum(y[i] == "a" for i in pru), 21)
        self.assertEqual(sum(y[i] == "b" for i in pru), 9)

    def test_pliegues_particionan(self):
        y = ["a"] * 23 + ["b"] * 17
        pliegues = pliegues_estratificados(y, 5, semilla=3)
        todos = [i for p in pliegues for i in p]
        self.assertEqual(sorted(todos), list(range(40)))
        for p in pliegues:
            self.assertIn(sum(y[i] == "b" for i in p), (3, 4))


class TestArbolSobreLaMuestra(unittest.TestCase):
    """Integración con el dataset de muestra de TransMilenio (una semana)."""

    @classmethod
    def setUpClass(cls):
        red = RedTransporte()
        cls.atributos = atributos_estaciones(red)
        X, y = preparar(unir_atributos(generar_dataset(red, dias=7, semilla=3), cls.atributos))
        ent, pru = division_estratificada(y, 0.3, semilla=1)
        cls.X_ent, cls.y_ent = [X[i] for i in ent], [y[i] for i in ent]
        cls.X_pru, cls.y_pru = [X[i] for i in pru], [y[i] for i in pru]

    def test_etiquetas_y_franjas(self):
        self.assertEqual([nivel_demanda(v) for v in (0, 249, 250, 799, 800)],
                         ["bajo", "bajo", "medio", "medio", "alto"])
        self.assertEqual([franja(h) for h in (4, 6, 12, 17, 22)],
                         ["madrugada", "pico_am", "valle", "pico_pm", "noche"])
        with self.assertRaises(ValueError):
            franja(2)
        x = ejemplo(self.atributos["Portal Norte"], 7, "habil", True)
        self.assertEqual(set(x), set(ATRIBUTOS))
        self.assertEqual((x["franja"], x["lluvia"], x["es_portal"]), ("pico_am", "si", "si"))

    def test_prediccion_truncada_igual_a_arbol_menos_profundo(self):
        profundo = ArbolDecision(profundidad_max=12, min_muestras_hoja=20).entrenar(self.X_ent, self.y_ent, ATRIBUTOS)
        for d in (2, 5):
            corto = ArbolDecision(profundidad_max=d, min_muestras_hoja=20).entrenar(self.X_ent, self.y_ent, ATRIBUTOS)
            self.assertEqual(profundo.predecir_lote(self.X_pru, d), corto.predecir_lote(self.X_pru))
            self.assertLessEqual(corto.contar()[2], d)

    def test_supera_a_las_lineas_base(self):
        arbol = ArbolDecision(profundidad_max=10, min_muestras_hoja=20).entrenar(
            self.X_ent, self.y_ent, ATRIBUTOS, clases=CLASES)
        acc_arbol = exactitud(self.y_pru, arbol.predecir_lote(self.X_pru))
        acc_oner = exactitud(self.y_pru, OneR().entrenar(self.X_ent, self.y_ent, ATRIBUTOS).predecir_lote(self.X_pru))
        acc_zeror = exactitud(self.y_pru, ZeroR().entrenar(self.X_ent, self.y_ent).predecir_lote(self.X_pru))
        self.assertGreater(acc_arbol, acc_oner + 0.10)
        self.assertGreater(acc_oner, acc_zeror)
        self.assertGreater(acc_arbol, 0.80)

    def test_json_ida_y_vuelta(self):
        arbol = ArbolDecision(profundidad_max=6, min_muestras_hoja=20).entrenar(self.X_ent, self.y_ent, ATRIBUTOS)
        copia = ArbolDecision.desde_json(arbol.a_json())
        self.assertEqual(copia.predecir_lote(self.X_pru), arbol.predecir_lote(self.X_pru))
        self.assertEqual([str(r) for r in copia.extraer_reglas()], [str(r) for r in arbol.extraer_reglas()])

    def test_validacion_cruzada(self):
        curva, elegida = validar_profundidad(self.X_ent[:4000], self.y_ent[:4000], ATRIBUTOS, range(1, 7),
                                             k=3, semilla=1, min_muestras_hoja=20)
        self.assertEqual([p.profundidad for p in curva], list(range(1, 7)))
        self.assertIn(elegida, range(1, 7))
        self.assertGreater(curva[-1].exactitud_validacion, curva[0].exactitud_validacion)
        entrenamiento = [p.exactitud_entrenamiento for p in curva]
        self.assertEqual(entrenamiento, sorted(entrenamiento))   # más profundo nunca acierta menos al entrenar
        # Regla de un error estándar: la menor profundidad a menos de un error estándar de la mejor
        mejor = max(curva, key=lambda p: p.exactitud_validacion)
        umbral = mejor.exactitud_validacion - mejor.error_estandar
        self.assertGreaterEqual(curva[elegida - 1].exactitud_validacion, umbral)
        self.assertTrue(all(p.exactitud_validacion < umbral for p in curva[:elegida - 1]))


if __name__ == "__main__":
    unittest.main()
