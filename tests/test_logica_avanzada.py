"""Pruebas avanzadas del motor de inferencia: comparación con un oráculo sobre programas
aleatorios, estratificación, hechos dinámicos, casos límite del analizador y explicaciones."""
import os
import random
import unittest

from sistema.logica import BaseConocimiento, ErrorLogico, formatear_hecho
from sistema.red import DIR_CONOCIMIENTO, RedTransporte
from tests.oraculos import cierre_transitivo


def kb_desde(texto: str) -> BaseConocimiento:
    kb = BaseConocimiento()
    kb.cargar_texto(texto)
    kb.inferir()
    return kb


ALCANZA = """
alcanza(X, Y) :- arista(X, Y).
alcanza(X, Z) :- arista(X, Y), alcanza(Y, Z).
inalcanzable(X, Y) :- nodo(X), nodo(Y), no alcanza(X, Y).
"""


def grafos_aleatorios(semilla, cantidad=40):
    """Grafos dirigidos pequeños (con ciclos y bucles) y su programa, con los hechos en desorden."""
    rng = random.Random(semilla)
    for _ in range(cantidad):
        nodos = list(range(rng.randint(1, 9)))
        aristas = {(rng.choice(nodos), rng.choice(nodos)) for _ in range(rng.randint(0, 2 * len(nodos)))}
        hechos = [f"nodo({n})." for n in nodos] + [f"arista({a}, {b})." for a, b in aristas]
        rng.shuffle(hechos)
        yield nodos, aristas, "\n".join(hechos) + ALCANZA


class TestDiferencial(unittest.TestCase):
    """El encadenamiento hacia adelante debe coincidir con un recorrido en amplitud escrito aparte."""

    def test_cierre_transitivo_igual_al_oraculo(self):
        for i, (nodos, aristas, programa) in enumerate(grafos_aleatorios(semilla=1)):
            with self.subTest(grafo=i, aristas=sorted(aristas)):
                obtenido = {(f["X"], f["Y"]) for f in kb_desde(programa).consultar("alcanza(X, Y)")}
                self.assertEqual(obtenido, cierre_transitivo(nodos, aristas))

    def test_negacion_sobre_un_predicado_recursivo(self):
        for i, (nodos, aristas, programa) in enumerate(grafos_aleatorios(semilla=2)):
            with self.subTest(grafo=i, aristas=sorted(aristas)):
                todos = {(a, b) for a in nodos for b in nodos}
                obtenido = {(f["X"], f["Y"]) for f in kb_desde(programa).consultar("inalcanzable(X, Y)")}
                self.assertEqual(obtenido, todos - cierre_transitivo(nodos, aristas))


class TestEstratificacion(unittest.TestCase):
    def test_tres_estratos_encadenados(self):
        kb = kb_desde('''
            base("x"). base("y"). d("x").
            c(X) :- d(X).
            b(X) :- base(X), no c(X).
            a(X) :- base(X), no b(X).
        ''')
        self.assertEqual(kb.estadisticas.estratos, 3)
        self.assertEqual(kb.consultar("b(X)"), [{"X": "y"}])
        self.assertEqual(kb.consultar("a(X)"), [{"X": "x"}])

    def test_ciclo_con_negacion_a_traves_de_varias_reglas(self):
        with self.assertRaisesRegex(ErrorLogico, "no estratificable"):
            kb_desde('n("a"). p(X) :- n(X), no q(X). q(X) :- r(X). r(X) :- p(X).')

    def test_estadisticas_de_la_inferencia(self):
        kb = kb_desde('''
            padre("a", "b"). padre("b", "c"). padre("c", "d").
            ancestro(X, Y) :- padre(X, Y).
            ancestro(X, Z) :- padre(X, Y), ancestro(Y, Z).
        ''')
        e = kb.estadisticas
        self.assertEqual((e.hechos_base, e.hechos_derivados, e.disparos, e.reglas, e.estratos), (3, 6, 6, 2, 1))
        red = RedTransporte()
        e = red.estadisticas
        self.assertEqual(e.hechos_base, len(red.kb.hechos_base))
        self.assertEqual(e.disparos, e.hechos_derivados)   # cada hecho derivado se cuenta una sola vez
        self.assertEqual(e.reglas, 15)
        self.assertGreaterEqual(e.estratos, 2)             # habilitada/1 depende de "no cerrada/1"
        self.assertGreaterEqual(e.iteraciones, e.estratos)


class TestHechosDinamicos(unittest.TestCase):
    def test_agregar_y_retirar_hechos_en_secuencia(self):
        """Con las reglas reales: tras cada cierre o reapertura, las conclusiones coinciden con las calculadas a mano."""
        estaciones = ["A", "B", "C", "D", "E", "F"]
        tramos = list(zip(estaciones, estaciones[1:]))
        kb = BaseConocimiento()
        kb.cargar_texto("\n".join(f'siguiente("{a}", "{b}", "T").' for a, b in tramos))
        kb.cargar_archivo(os.path.join(DIR_CONOCIMIENTO, "reglas.kb"))
        rng = random.Random(4)
        cerradas = set()
        for paso in range(30):
            e = rng.choice(estaciones)
            if e in cerradas:
                kb.retirar_hecho("cerrada", e)
                cerradas.discard(e)
            else:
                kb.agregar_hecho("cerrada", e)
                cerradas.add(e)
            with self.subTest(paso=paso, cerradas=sorted(cerradas)):
                self.assertEqual({f["E"] for f in kb.consultar("habilitada(E)")}, set(estaciones) - cerradas)
                abiertos = [(a, b) for a, b in tramos if not {a, b} & cerradas]
                self.assertEqual({(f["A"], f["B"]) for f in kb.consultar("movimiento(A, B, T)")},
                                 set(abiertos) | {(b, a) for a, b in abiertos})


ALFABETO = "aZ09 _-.,;:()%'\"\\/ñÑçÉé·→"


class TestSintaxis(unittest.TestCase):
    def assertIdaYVuelta(self, *argumentos):
        texto = formatear_hecho(("p", argumentos)) + "."
        kb = kb_desde(texto)
        self.assertEqual(list(kb.buscar("p", *[None] * len(argumentos))), [argumentos], texto)

    def test_ida_y_vuelta_formatear_y_analizar(self):
        """Todo hecho escrito con formatear_hecho se vuelve a leer igual, con comillas o barras invertidas."""
        for valor in ["a\\b", "fin\\", "\\", '\\"', 'comilla " doble', "comilla ' simple", "% no es comentario"]:
            with self.subTest(valor=valor):
                self.assertIdaYVuelta(valor)
        rng = random.Random(7)
        for i in range(200):
            cadena = "".join(rng.choice(ALFABETO) for _ in range(rng.randint(0, 12)))
            entero, decimal = rng.randint(-1000, 1000), round(rng.uniform(-100, 100), rng.randint(1, 4))
            with self.subTest(caso=i, cadena=cadena):
                self.assertIdaYVuelta(cadena, entero, decimal)

    def test_variables_anonimas_son_independientes(self):
        # Si los dos "_" fueran la misma variable, haría falta q(_, "b") y r("b", _): no hay resultado
        kb = kb_desde('q("a", "b"). r("c", "a"). p(X) :- q(X, _), r(_, X).')
        self.assertEqual(kb.consultar("p(X)"), [{"X": "a"}])

    def test_aridades_distintas_no_se_mezclan(self):
        kb = kb_desde('p("a"). p("a", "b").')
        self.assertEqual(kb.consultar("p(X)"), [{"X": "a"}])
        self.assertEqual(kb.consultar("p(X, Y)"), [{"X": "a", "Y": "b"}])

    def test_predicado_integrado_igual(self):
        kb = kb_desde("n(1). n(2). par(X, Y) :- n(X), n(Y), igual(X, Y).")
        self.assertEqual(kb.consultar("par(X, Y)"), [{"X": 1, "Y": 1}, {"X": 2, "Y": 2}])

    def test_mensajes_de_error_con_linea_y_causa(self):
        casos = [('a("x").\nb("y")\nc("z").', "Línea 3: se esperaba '.'"),
                 ("p(@).", "carácter inesperado '@'"),
                 ('\n\nP("x").', "Línea 3: el predicado 'P' debe iniciar en minúscula"),
                 ('p("x") :- .', "se esperaba 'ident'")]
        for texto, mensaje in casos:
            with self.subTest(texto=texto):
                with self.assertRaises(ErrorLogico) as ctx:
                    kb_desde(texto)
                self.assertIn(mensaje, str(ctx.exception))

    def test_consulta_con_negacion_insegura(self):
        kb = kb_desde('p("a"). q("b").')
        with self.assertRaisesRegex(ErrorLogico, "deben aparecer en un literal positivo"):
            kb.consultar("p(X), no q(Y)")

    def test_buscar_con_comodin_en_el_primer_argumento(self):
        kb = kb_desde('siguiente("A", "B", "T"). siguiente("B", "C", "T"). siguiente("Z", "C", "U").')
        self.assertEqual(list(kb.buscar("siguiente", None, "C", None)), [("B", "C", "T"), ("Z", "C", "U")])


CADENA = '''
padre("a", "b"). padre("b", "c"). padre("c", "d"). padre("d", "e").
ancestro(X, Y) :- padre(X, Y).
ancestro(X, Z) :- padre(X, Y), ancestro(Y, Z).
'''


class TestExplicaciones(unittest.TestCase):
    def test_negacion_se_muestra_como_verificada(self):
        kb = kb_desde('estacion("A"). habilitada(E) :- estacion(E), no cerrada(E).')
        texto = kb.explicar(("habilitada", ("A",)))
        self.assertIn('estacion("A")   [hecho]', texto)
        self.assertIn('no cerrada("A")   [verificado]', texto)

    def test_profundidad_maxima_recorta_la_prueba(self):
        kb = kb_desde(CADENA)
        corta = kb.explicar(("ancestro", ("a", "e")), profundidad_max=2)
        self.assertIn('ancestro("c", "e")', corta)
        self.assertNotIn('padre("c", "d")', corta)
        self.assertIn('padre("d", "e")', kb.explicar(("ancestro", ("a", "e"))))

    def test_mismo_resultado_con_cualquier_orden_de_los_hechos(self):
        # ancestro("a", "d") tiene dos demostraciones (por "b" y por "x"): la explicación elige siempre la misma
        hechos = ['padre("a", "b").', 'padre("b", "c").', 'padre("a", "x").', 'padre("x", "c").', 'padre("c", "d").']
        reglas = "ancestro(X, Y) :- padre(X, Y). ancestro(X, Z) :- padre(X, Y), ancestro(Y, Z)."
        resultados = []
        for semilla in range(5):
            orden = list(hechos)
            random.Random(semilla).shuffle(orden)
            kb = kb_desde(" ".join(orden) + reglas)
            resultados.append((kb.explicar(("ancestro", ("a", "d"))), kb.consultar("ancestro(X, Y)"),
                               kb.estadisticas))
        for r in resultados[1:]:
            self.assertEqual(r, resultados[0])


if __name__ == "__main__":
    unittest.main()
