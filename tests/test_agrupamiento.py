"""Pruebas de k-medias, agrupamiento jerárquico, silueta e índice de Rand ajustado."""
import random
import unittest

from actividad4.no_supervisado import (alinear, hechos_perfiles, nombrar_grupos, ordenar_por_tamano,
                                       perfiles_estaciones)
from aprendizaje.agrupamiento import (ENLACES, centroides, cortar, estandarizar, indice_rand_ajustado, jerarquico,
                                      kmedias, silueta, sse)
from aprendizaje.datos import atributos_estaciones, generar_dataset, vocacion_latente
from sistema.logica import BaseConocimiento
from sistema.red import RedTransporte


def manchas(semilla=1, por_grupo=20):
    """Tres nubes de puntos bien separadas y su etiqueta verdadera."""
    rng = random.Random(semilla)
    centros = [(0, 0), (10, 0), (0, 10)]
    X, y = [], []
    for g, (cx, cy) in enumerate(centros):
        for _ in range(por_grupo):
            X.append([rng.gauss(cx, 0.5), rng.gauss(cy, 0.5)])
            y.append(g)
    return X, y


class TestAlgoritmos(unittest.TestCase):
    def setUp(self):
        self.X, self.y = manchas()

    def test_kmedias_recupera_los_grupos(self):
        r = kmedias(self.X, 3, semilla=0)
        self.assertAlmostEqual(indice_rand_ajustado(r.etiquetas, self.y), 1.0)
        self.assertEqual(sorted(r.etiquetas.count(g) for g in range(3)), [20, 20, 20])

    def test_jerarquico_recupera_los_grupos_con_todos_los_enlaces(self):
        for enlace in ENLACES:
            with self.subTest(enlace=enlace):
                fusiones = jerarquico(self.X, enlace)
                self.assertEqual(len(fusiones), len(self.X) - 1)
                self.assertEqual(fusiones[-1][3], len(self.X))
                self.assertAlmostEqual(indice_rand_ajustado(cortar(fusiones, len(self.X), 3), self.y), 1.0)

    def test_los_cuatro_enlaces_son_monotonos(self):
        """Ninguna fusión ocurre a menor altura que la anterior (sin inversiones en el dendrograma)."""
        for enlace in ENLACES:
            with self.subTest(enlace=enlace):
                alturas = [f[2] for f in jerarquico(self.X, enlace)]
                self.assertEqual(alturas, sorted(alturas))

    def test_cortes_extremos(self):
        fusiones = jerarquico(self.X)
        n = len(self.X)
        self.assertEqual(cortar(fusiones, n, n), list(range(n)))
        self.assertEqual(set(cortar(fusiones, n, 1)), {0})

    def test_silueta_maxima_en_el_k_verdadero(self):
        siluetas = {k: silueta(self.X, kmedias(self.X, k, semilla=0).etiquetas) for k in range(2, 7)}
        self.assertEqual(max(siluetas, key=siluetas.get), 3)
        self.assertTrue(all(-1 <= s <= 1 for s in siluetas.values()))
        self.assertGreater(siluetas[3], 0.8)

    def test_sse_disminuye_con_k(self):
        self.assertLess(kmedias(self.X, 3, semilla=0).sse, kmedias(self.X, 1, semilla=0).sse)
        r = kmedias(self.X, 3, semilla=0)
        self.assertAlmostEqual(r.sse, sse(self.X, r.etiquetas))

    def test_determinista_con_semilla(self):
        self.assertEqual(kmedias(self.X, 4, semilla=5).etiquetas, kmedias(self.X, 4, semilla=5).etiquetas)

    def test_estandarizar(self):
        Z, medias, desv = estandarizar([[1, 100], [2, 200], [3, 300], [4, 400]])
        for j in range(2):
            col = [z[j] for z in Z]
            self.assertAlmostEqual(sum(col) / len(col), 0.0)
            self.assertAlmostEqual(sum(v * v for v in col) / len(col), 1.0)
        self.assertEqual(medias, [2.5, 250.0])

    def test_indice_rand_ajustado(self):
        self.assertAlmostEqual(indice_rand_ajustado([0, 0, 1, 1, 2, 2], [2, 2, 0, 0, 1, 1]), 1.0)
        self.assertLess(indice_rand_ajustado([0, 0, 0, 1, 1, 1], [0, 1, 0, 1, 0, 1]), 0.1)
        with self.assertRaises(ValueError):
            indice_rand_ajustado([0, 1], [0])

    def test_centroides(self):
        self.assertEqual(centroides([[0, 0], [2, 2], [10, 10]], [0, 0, 1]), [[1, 1], [10, 10]])


class TestAgrupamientoDeEstaciones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        cls.perfiles = perfiles_estaciones(generar_dataset(cls.red, dias=14, semilla=42))
        cls.estaciones = [p.estacion for p in cls.perfiles]
        cls.X = [p.vector() for p in cls.perfiles]
        cls.Z, _, _ = estandarizar(cls.X)

    def test_un_perfil_por_estacion(self):
        self.assertEqual(self.estaciones, self.red.estaciones)
        for p in self.perfiles:
            self.assertAlmostEqual(sum(p.entradas_hora), 100.0)
            self.assertTrue(0 < p.atributos["pico_am_entradas"] < 1)

    def test_grupos_recuperan_la_vocacion_oculta(self):
        etiquetas = ordenar_por_tamano(kmedias(self.Z, 5, semilla=42).etiquetas)
        atrib = atributos_estaciones(self.red)
        vocacion = [vocacion_latente(e, atrib[e]) for e in self.estaciones]
        self.assertGreater(indice_rand_ajustado(etiquetas, vocacion), 0.6)
        nombres = {ident for _, ident in nombrar_grupos(centroides(self.X, etiquetas), centroides(self.Z, etiquetas))}
        self.assertTrue({"residencial", "empleo"} <= nombres)

    def test_nombres_repetidos_se_numeran_todos(self):
        # Dos centroides con el mismo patrón de empleo -> "Empleo / oficinas 1" y "2"
        empleo = [4.0, 0.1, 0.5, 0.5, 0.1, 0.3]
        z = [0.0] * 6
        nombres = nombrar_grupos([empleo, empleo], [z, z])
        self.assertEqual([i for _, i in nombres], ["empleo_1", "empleo_2"])

    def test_alinear_conserva_la_particion(self):
        a = [0, 0, 1, 1, 2, 2]
        b = [1, 1, 2, 2, 0, 0]
        self.assertEqual(alinear(a, b), a)

    def test_perfiles_se_cargan_en_la_base_de_conocimiento(self):
        etiquetas = kmedias(self.Z, 3, semilla=1).etiquetas
        texto = hechos_perfiles(self.estaciones, etiquetas, ["uno", "dos", "tres"])
        kb = BaseConocimiento()
        kb.cargar_texto(texto)
        filas = kb.consultar("perfil_estacion(E, P)")
        self.assertEqual(len(filas), len(self.estaciones))
        self.assertTrue(kb.es_cierto("perfil_estacion", self.estaciones[0], ["uno", "dos", "tres"][etiquetas[0]]))


if __name__ == "__main__":
    unittest.main()
