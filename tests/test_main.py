"""Pruebas del punto de entrada único (main.py): ayuda, reenvío a las actividades y menú interactivo."""
import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import main

PERFILES = "actividad4/resultados/perfiles.kb"
# rich decide los colores al importarse: si las pruebas corren en una terminal, la
# salida capturada trae códigos ANSI, que se quitan antes de comparar
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def capturar(funcion):
    """Ejecuta funcion con un ancho de consola fijo y devuelve (resultado, salida en texto plano)."""
    salida = io.StringIO()
    with mock.patch.dict(os.environ, {"COLUMNS": "120"}), redirect_stdout(salida), redirect_stderr(salida):
        resultado = funcion()
    return resultado, ANSI.sub("", salida.getvalue())


def ejecutar(argv):
    return capturar(lambda: main.main(argv))


def sesion(respuestas):
    """Recorre el menú con respuestas simuladas; al acabarse, input lanza EOFError (fin de la entrada)."""
    entradas = iter(respuestas)

    def leer(_mensaje=""):
        try:
            return next(entradas)
        except StopIteration:
            raise EOFError from None

    with mock.patch("builtins.input", leer):
        return capturar(main.modo_interactivo)[1]


class TestLineaDeComandos(unittest.TestCase):
    def test_ayuda_organizada_por_actividad(self):
        salida = io.StringIO()
        with redirect_stdout(salida), self.assertRaises(SystemExit):
            main.main(["-h"])
        for texto in ("Actividad 2", "Actividad 3", "Actividad 4", "actividad3 COMANDO", "consultar"):
            self.assertIn(texto, salida.getvalue())

    def test_reenvio_a_la_actividad_3(self):
        codigo, texto = ejecutar(["actividad3", "reglas", "--clase", "alto", "--top", "2"])
        self.assertEqual(codigo, 0)
        self.assertIn("ENTONCES alto", texto)

    def test_consultar_con_los_perfiles_de_la_actividad_4(self):
        codigo, texto = ejecutar(["consultar", "perfil_estacion(E, P), estacion_de_integracion(E)",
                                  "--con", PERFILES])
        self.assertEqual(codigo, 0)
        self.assertIn("Ricaurte", texto)
        codigo, texto = ejecutar(["consultar", "perfil_estacion(E, P)", "--con", "no/existe.kb"])
        self.assertEqual(codigo, 1)
        self.assertIn("No existe el archivo", texto)

    def test_explicar_muestra_los_corchetes(self):
        # rich no debe tomar [regla R9] ni [hecho] como etiquetas de estilo
        codigo, texto = ejecutar(["explicar", "transbordo", "Ricaurte", "E", "F"])
        self.assertEqual(codigo, 0)
        self.assertIn('transbordo("Ricaurte", "E", "F")   [regla R9]', texto)
        self.assertIn("[hecho]", texto)

    def test_escenarios_generan_el_reporte_con_todo_aprobado(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "resultados_pruebas.md")
            codigo, texto = ejecutar(["escenarios", "--salida", ruta])
            with open(ruta, encoding="utf-8") as f:
                reporte = f.read()
        self.assertEqual(codigo, 0)
        self.assertIn("10/10 aprobadas.", texto)
        self.assertEqual(reporte.count("**Veredicto:** APROBADA"), 10)
        self.assertIn("**Total: 10/10 pruebas aprobadas.**", reporte)

    def test_estaciones_de_una_troncal_en_orden(self):
        codigo, texto = ejecutar(["estaciones", "--troncal", "e"])    # el código se acepta en minúscula
        self.assertEqual(codigo, 0)
        filas = re.findall(r"^│\s*\d+\s*│\s*([^│]+?)\s*│", texto, re.M)
        self.assertEqual(filas, ["Calle 100", "La Castellana", "NQS Calle 75", "Av. Chile", "7 de Agosto",
                                 "Movistar Arena", "Campín", "U. Nacional", "Av. El Dorado", "CAD", "Paloquemao",
                                 "Ricaurte"])
        self.assertIn("Ramal/interconector: NQS Calle 75 → Escuela Militar", texto)
        codigo, texto = ejecutar(["estaciones", "--troncal", "X"])
        self.assertEqual(codigo, 1)
        self.assertIn("Troncal desconocida: X", texto)

    def test_errores_devuelven_codigo_1_con_ayuda(self):
        casos = [(["ruta", "Calle 10", "Portal Norte"], "'Calle 10' es ambiguo. ¿Quiso decir: Calle 100, Calle 106?"),
                 (["ruta", "Portal Nrte", "Calle 100"], "¿Quiso decir: Portal Norte"),
                 (["consultar", "p(X"], "Línea 1: se esperaba ')'")]
        for argv, mensaje in casos:
            with self.subTest(argv=argv):
                codigo, texto = ejecutar(argv)
                self.assertEqual(codigo, 1)
                self.assertIn(mensaje, texto)

    def test_comparar_las_cuatro_estrategias(self):
        codigo, texto = ejecutar(["comparar", "Escuela Militar", "U. Nacional"])
        self.assertEqual(codigo, 0)
        for nombre in ("A* (A estrella)", "Costo uniforme", "Primero el mejor voraz", "Primero en amplitud"):
            self.assertIn(nombre, texto)
        self.assertIn("Ruta encontrada por A*: Escuela Militar → NQS Calle 75", texto)


class TestMenuInteractivo(unittest.TestCase):
    def test_submenu_agrupado_en_secciones(self):
        texto = sesion(["2", "0", "0"])
        for seccion in ("BÚSQUEDA DE RUTAS", "BASE DE CONOCIMIENTO", "RED DE ESTACIONES", "REGLAS Y PRUEBAS"):
            self.assertIn(seccion, texto)
        self.assertIn("Estaciones cerradas: ninguna", texto)

    def test_ruta_en_la_actividad_2(self):
        texto = sesion(["2", "1", "portal norte", "calle 100", "", "", "0", "0"])
        self.assertIn("ACTIVIDAD 2", texto)
        self.assertIn("Resumen:", texto)
        self.assertIn('Comando equivalente: python main.py ruta "Portal Norte" "Calle 100" -d', texto)
        self.assertIn("Hasta luego", texto)

    def test_prediccion_con_entrada_invalida(self):
        texto = sesion(["3", "3", "Portal Norte", "99", "6", "", "", "", "0", "0"])
        self.assertIn("Escriba un número entre 4 y 22", texto)
        self.assertIn("Nivel de demanda previsto", texto)

    def test_estacion_cerrada_se_comparte_entre_actividades(self):
        texto = sesion(["2", "5", "Paloquemao", "0", "3", "5", "Portal Norte", "Ricaurte", "8", "", "", "",
                        "0", "0"])
        self.assertIn("Estaciones cerradas: Paloquemao", texto)
        self.assertIn("actividad3 ruta \"Portal Norte\" Ricaurte --hora 8 --dia habil --cerrar Paloquemao",
                      texto)

    def test_perfiles_de_la_actividad_4_en_la_base_de_conocimiento(self):
        with mock.patch.object(main, "_archivos_perfiles", return_value=[(PERFILES, "k elegido por la silueta")]):
            texto = sesion(["4", "4", "", "", "0", "0"])
        self.assertIn(f"--con {PERFILES}", texto)
        self.assertIn("Ricaurte", texto)

    def test_archivos_de_perfiles_en_orden_natural(self):
        """k2, k5, k10 (no k10, k2, k5); se omiten las carpetas que no son kN o no tienen perfiles.kb."""
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "actividad4", "resultados")
            for carpeta in ("", "k10", "k2", "k5", "kx"):
                os.makedirs(os.path.join(base, carpeta), exist_ok=True)
                with open(os.path.join(base, carpeta, "perfiles.kb"), "w", encoding="utf-8"):
                    pass
            os.makedirs(os.path.join(base, "k3"))
            with mock.patch.object(main, "DIR_RAIZ", tmp):
                archivos = main._archivos_perfiles("real")
        self.assertEqual(archivos, [("actividad4/resultados/perfiles.kb", "k elegido por la silueta"),
                                    ("actividad4/resultados/k2/perfiles.kb", "k = 2, fijado con -k"),
                                    ("actividad4/resultados/k5/perfiles.kb", "k = 5, fijado con -k"),
                                    ("actividad4/resultados/k10/perfiles.kb", "k = 10, fijado con -k")])

    def test_opcion_invalida_y_fin_de_la_entrada(self):
        texto = sesion(["9", "2", "x"])
        self.assertIn("Opción no válida", texto)
        self.assertIn("Hasta luego", texto)


if __name__ == "__main__":
    unittest.main()
