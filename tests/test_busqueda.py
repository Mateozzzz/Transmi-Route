"""Pruebas de integración: base de conocimiento de TransMilenio + búsqueda."""
import random
import unittest

from sistema.busqueda import ProblemaRuta, a_estrella, buscar_ruta, costo_uniforme
from sistema.red import RedTransporte
from tests.oraculos import aristas_del_espacio, dijkstra_completo, transbordos_y_minutos

# Pares de referencia + una muestra fija: A* sobre los 7.225 pares tardaría unos 14 s
PARES_FIJOS = [("Portal Norte", "Portal Américas"), ("Portal 80", "Universidades"), ("Portal El Dorado", "Calle 72"),
               ("Tercer Milenio", "Toberín"), ("Portal 80", "Portal Américas"), ("Portal 80", "Museo del Oro")]


class TestRed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()

    def test_todas_las_estaciones_tienen_coordenadas(self):
        self.assertGreater(len(self.red.estaciones), 80)
        for e in self.red.estaciones:
            self.assertIn(e, self.red.coordenadas)

    def test_transbordos_inferidos_por_las_reglas(self):
        kb = self.red.kb
        self.assertTrue(kb.es_cierto("transbordo", "Ricaurte", "E", "F"))
        self.assertTrue(kb.es_cierto("transbordo", "Av. Jiménez", "A", "J"))
        self.assertTrue(kb.es_cierto("transbordo", "Calle 100", "B", "E"))
        self.assertFalse(kb.es_cierto("transbordo", "Calle 45", "A", "B"))

    def test_tramos_bidireccionales(self):
        kb = self.red.kb
        self.assertTrue(kb.es_cierto("movimiento", "Toberín", "Portal Norte", "B"))
        self.assertTrue(kb.es_cierto("movimiento", "Portal Norte", "Toberín", "B"))

    def test_resolver_nombre_sin_tildes(self):
        self.assertEqual(self.red.resolver_nombre("heroes"), "Héroes")
        self.assertEqual(self.red.resolver_nombre("AV JIMENEZ"), "Av. Jiménez")
        with self.assertRaises(ValueError):
            self.red.resolver_nombre("calle")        # ambiguo
        with self.assertRaises(ValueError):
            self.red.resolver_nombre("Estación X")   # inexistente


class TestBusqueda(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        rng = random.Random(2026)
        cls.pares = PARES_FIJOS + [(rng.choice(cls.red.estaciones), rng.choice(cls.red.estaciones))
                                   for _ in range(150)]
        # Oráculo: costo real desde cada estación a todas las demás (Dijkstra completo, sin prueba de meta)
        cls.optimo = {c: {o: dijkstra_completo(cls.red, o, c) for o in cls.red.estaciones}
                      for c in ProblemaRuta.CRITERIOS}

    def test_misma_troncal_sin_transbordos(self):
        r = buscar_ruta(self.red, "Portal Norte", "Calle 100")
        self.assertTrue(r.encontrado)
        self.assertEqual(r.transbordos, 0)
        self.assertEqual(r.paradas, 11)

    def test_a_estrella_es_optimo(self):
        """A* encuentra el costo mínimo que calcula el oráculo, con los dos criterios."""
        for criterio in ProblemaRuta.CRITERIOS:
            for o, d in self.pares:
                with self.subTest(criterio=criterio, o=o, d=d):
                    r = a_estrella(ProblemaRuta(self.red, o, d, criterio))
                    self.assertAlmostEqual(r.costo, self.optimo[criterio][o][d], places=6)

    def test_a_estrella_expande_menos_nodos(self):
        """Con una heurística consistente, A* nunca expande más nodos que costo uniforme."""
        total_a = total_cu = 0
        for o, d in self.pares:
            p = ProblemaRuta(self.red, o, d)
            a, cu = a_estrella(p).nodos_expandidos, costo_uniforme(p).nodos_expandidos
            with self.subTest(o=o, d=d):
                self.assertLessEqual(a, cu)
            total_a, total_cu = total_a + a, total_cu + cu
        self.assertLess(total_a, total_cu)

    def test_heuristica_admisible(self):
        """h(n) nunca sobreestima el costo real hasta el destino: los 7.225 pares de estaciones.
        Basta el estado inicial de cada estación: desde él se aborda gratis cualquier troncal,
        así que ningún otro estado de la misma estación llega más barato al destino."""
        for criterio in ProblemaRuta.CRITERIOS:
            excesos = [(o, d) for o in self.red.estaciones for d in self.red.estaciones
                       if self.red.heuristica(o, d) > self.optimo[criterio][o][d] + 1e-9]
            self.assertEqual(excesos, [], criterio)

    def test_heuristica_consistente(self):
        """h(n) ≤ c(n, n') + h(n') en cada arista del espacio de estados y para cada destino."""
        aristas = aristas_del_espacio(self.red)
        estaciones = self.red.estaciones
        h = {(e, d): self.red.heuristica(e, d) for e in estaciones for d in estaciones}
        self.assertGreater(len(aristas), len(estaciones))
        violaciones = [(s, s2, d) for s, s2, costo in aristas for d in estaciones
                       if h[(s.estacion, d)] > costo + h[(s2.estacion, d)] + 1e-9]
        self.assertEqual(violaciones, [])

    def test_voraz_puede_ser_suboptima(self):
        voraz = buscar_ruta(self.red, "Escuela Militar", "U. Nacional", "voraz")
        estrella = buscar_ruta(self.red, "Escuela Militar", "U. Nacional", "a_estrella")
        self.assertGreater(voraz.minutos, estrella.minutos)

    def test_conexion_peatonal(self):
        r = buscar_ruta(self.red, "Portal El Dorado", "Museo del Oro")
        self.assertIn("caminar", [p.accion for p in r.pasos])

    def test_estacion_cerrada_obliga_a_replanificar(self):
        normal = buscar_ruta(self.red, "Portal Norte", "Ricaurte")
        self.assertIn("Paloquemao", normal.estaciones_ruta)
        red_cerrada = RedTransporte(cerradas=["Paloquemao"])
        desvio = buscar_ruta(red_cerrada, "Portal Norte", "Ricaurte")
        self.assertTrue(desvio.encontrado)
        self.assertNotIn("Paloquemao", desvio.estaciones_ruta)
        self.assertGreaterEqual(desvio.costo, normal.costo)

    def test_sin_ruta(self):
        red = RedTransporte(cerradas=["Toberín"])
        self.assertFalse(buscar_ruta(red, "Portal Norte", "Calle 100").encontrado)

    def test_origen_o_destino_cerrado_es_error(self):
        red = RedTransporte(cerradas=["Calle 100"])
        with self.assertRaises(ValueError):
            buscar_ruta(red, "Calle 100", "Portal Norte")

    def test_origen_igual_destino(self):
        r = buscar_ruta(self.red, "Calle 45", "Calle 45")
        self.assertTrue(r.encontrado)
        self.assertEqual(r.pasos, [])

    def test_criterio_transbordos_minimiza_primero_los_transbordos(self):
        """Con -c transbordos, la ruta tiene los menos transbordos posibles y, entre esas, el menor tiempo."""
        for o, d in self.pares[:40]:
            with self.subTest(o=o, d=d):
                t = buscar_ruta(self.red, o, d, criterio="tiempo")
                m = buscar_ruta(self.red, o, d, criterio="transbordos")
                transbordos, minutos = transbordos_y_minutos(self.red, o, d)
                self.assertEqual(m.transbordos, transbordos)
                self.assertAlmostEqual(m.minutos, minutos, places=6)
                self.assertLessEqual(m.transbordos, t.transbordos)


if __name__ == "__main__":
    unittest.main()
