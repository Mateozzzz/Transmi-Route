"""Pruebas avanzadas de la red y la búsqueda (Actividad 2): cifras de la base de conocimiento,
validez de cada paso de las rutas, comparación con oráculos y pruebas metamórficas."""
import random
import unittest

from sistema.busqueda import A_PIE, ALGORITMOS, PENALIZACION_TRANSBORDO, ProblemaRuta, buscar_ruta
from sistema.red import RedTransporte, normalizar
from tests.oraculos import dijkstra_completo, menos_acciones


def pares_aleatorios(red, cantidad, semilla):
    rng = random.Random(semilla)
    return [(rng.choice(red.estaciones), rng.choice(red.estaciones)) for _ in range(cantidad)]


class TestConocimientoDeLaRed(unittest.TestCase):
    """Las cifras y conclusiones que documenta el README salen de la base de conocimiento."""

    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        cls.kb = cls.red.kb

    def contar(self, predicado, aridad):
        return len(list(self.kb.buscar(predicado, *[None] * aridad)))

    def test_cifras_documentadas(self):
        self.assertEqual(self.contar("siguiente", 3), 85)
        self.assertEqual(len(self.red.estaciones), 85)
        self.assertEqual(len(self.red.troncales), 7)
        self.assertEqual(self.contar("portal", 1), 4)
        self.assertEqual(self.contar("conexion_peatonal", 3), 1)
        self.assertEqual(self.contar("parametro", 2), 3)
        self.assertEqual(len(self.kb.reglas), 15)

    def test_estaciones_de_transbordo_inferidas(self):
        """Ninguna está escrita a mano: las reglas las deducen de los tramos."""
        transbordo = {e for e, _, _ in self.kb.buscar("transbordo", None, None, None)}
        self.assertEqual(transbordo, {"Ricaurte", "Av. Jiménez", "Héroes", "Calle 100", "Escuela Militar"})

    def test_una_cabecera_por_troncal(self):
        filas = self.kb.consultar("cabecera(E, T)")
        self.assertEqual(len(filas), 7)
        self.assertEqual({f["T"]: f["E"] for f in filas},
                         {"A": "Héroes", "B": "Portal Norte", "D": "Portal 80", "E": "Calle 100",
                          "F": "Av. Jiménez", "J": "Av. Jiménez", "K": "Portal El Dorado"})

    def test_red_conexa(self):
        for origen in self.red.estaciones:
            with self.subTest(origen=origen):
                self.assertEqual(set(dijkstra_completo(self.red, origen)), set(self.red.estaciones))

    def test_cada_estacion_se_resuelve_sin_tildes_ni_mayusculas(self):
        for e in self.red.estaciones:
            for variante in (e.upper(), e.lower(), normalizar(e), normalizar(e).upper()):
                with self.subTest(variante=variante):
                    self.assertEqual(self.red.resolver_nombre(variante), e)


class TestRutasValidas(unittest.TestCase):
    """Cada ruta de cada algoritmo, con los dos criterios, es un recorrido que la base permite."""

    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        cls.rutas = [(o, d, a, c, buscar_ruta(cls.red, o, d, a, c))
                     for o, d in pares_aleatorios(cls.red, 50, semilla=11)
                     for a in ALGORITMOS for c in ProblemaRuta.CRITERIOS]

    def test_cada_paso_esta_justificado_por_la_base(self):
        kb = self.red.kb
        for o, d, algoritmo, criterio, r in self.rutas:
            with self.subTest(o=o, d=d, algoritmo=algoritmo, criterio=criterio):
                self.assertTrue(r.encontrado)
                estacion, troncal = o, None
                for p in r.pasos:
                    self.assertEqual(p.desde, estacion)
                    if p.accion == "viajar":
                        self.assertEqual(p.troncal, troncal)
                        self.assertTrue(kb.es_cierto("movimiento", p.desde, p.hacia, p.troncal))
                        self.assertAlmostEqual(p.minutos, self.red.tiempo_tramo(p.desde, p.hacia))
                    elif p.accion == "transbordo":
                        self.assertTrue(kb.es_cierto("transbordo", p.desde, troncal, p.troncal))
                    elif p.accion == "abordar":
                        self.assertIn(troncal, (None, A_PIE))     # solo al salir o después de caminar
                        self.assertTrue(kb.es_cierto("puede_abordar", p.desde, p.troncal))
                    else:
                        self.assertEqual(p.accion, "caminar")
                        self.assertTrue(kb.es_cierto("caminata", p.desde, p.hacia, int(p.minutos)))
                    estacion = p.hacia
                    troncal = A_PIE if p.accion == "caminar" else p.troncal
                self.assertEqual(estacion, d)
                self.assertEqual((r.estaciones_ruta[0], r.estaciones_ruta[-1]), (o, d))

    def test_costo_igual_a_la_suma_de_los_pasos(self):
        for o, d, algoritmo, criterio, r in self.rutas:
            with self.subTest(o=o, d=d, algoritmo=algoritmo, criterio=criterio):
                extra = PENALIZACION_TRANSBORDO * r.transbordos if criterio == "transbordos" else 0.0
                self.assertAlmostEqual(r.costo, r.minutos + extra, places=6)

    def test_amplitud_usa_el_menor_numero_de_acciones(self):
        acciones = {}
        for o, d, algoritmo, criterio, r in self.rutas:
            acciones.setdefault((o, d), {})[(algoritmo, criterio)] = len(r.pasos)
        for (o, d), por_algoritmo in acciones.items():
            with self.subTest(o=o, d=d):
                minimo = menos_acciones(self.red, o, d)
                for criterio in ProblemaRuta.CRITERIOS:
                    self.assertEqual(por_algoritmo[("amplitud", criterio)], minimo)
                self.assertGreaterEqual(min(por_algoritmo.values()), minimo)

    def test_voraz_nunca_mejora_al_optimo(self):
        optimo = {(o, d, c): r.costo for o, d, a, c, r in self.rutas if a == "a_estrella"}
        peores = 0
        for o, d, a, c, r in self.rutas:
            if a == "voraz":
                with self.subTest(o=o, d=d, criterio=c):
                    self.assertGreaterEqual(r.costo, optimo[(o, d, c)] - 1e-9)
                peores += r.costo > optimo[(o, d, c)] + 1e-9
        self.assertGreater(peores, 0)    # en la muestra también hay casos en que es estrictamente peor


class TestMetamorficas(unittest.TestCase):
    """Cerrar una estación cambia la red de una forma conocida, así que se puede predecir el efecto."""

    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        cls.casos = []
        rng = random.Random(5)
        while len(cls.casos) < 6:
            o, d = rng.sample(cls.red.estaciones, 2)
            r = buscar_ruta(cls.red, o, d)
            if len(r.estaciones_ruta) >= 4:
                cls.casos.append((o, d, r))

    def test_cerrar_una_estacion_fuera_de_la_ruta_no_cambia_el_costo(self):
        """La ruta óptima sigue disponible y cerrar no crea caminos nuevos: el costo no cambia."""
        rng = random.Random(8)
        for o, d, r in self.casos:
            cerrada = rng.choice([e for e in self.red.estaciones if e not in r.estaciones_ruta])
            with self.subTest(o=o, d=d, cerrada=cerrada):
                nueva = buscar_ruta(RedTransporte(cerradas=[cerrada]), o, d)
                self.assertTrue(nueva.encontrado)
                self.assertAlmostEqual(nueva.costo, r.costo, places=9)

    def test_cerrar_una_estacion_de_la_ruta_no_la_abarata(self):
        """Sin una estación de la ruta, o hay un desvío igual o más caro, o el oráculo confirma que no hay ruta."""
        rng = random.Random(9)
        desvios = 0
        for o, d, r in self.casos:
            cerrada = rng.choice(r.estaciones_ruta[1:-1])
            with self.subTest(o=o, d=d, cerrada=cerrada):
                red = RedTransporte(cerradas=[cerrada])
                nueva = buscar_ruta(red, o, d)
                if nueva.encontrado:
                    desvios += 1
                    self.assertGreaterEqual(nueva.costo, r.costo - 1e-9)
                    self.assertNotIn(cerrada, nueva.estaciones_ruta)
                else:
                    self.assertNotIn(d, dijkstra_completo(red, o))
        self.assertGreater(desvios, 0)


if __name__ == "__main__":
    unittest.main()
