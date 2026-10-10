"""Los resultados publicados se reproducen con el código actual: ejemplos del README, datos
de datos/, modelos y reportes de las Actividades 3 y 4, sin depender del hash de Python.

Si una prueba falla después de un cambio intencional, hay que regenerar lo publicado con
el comando correspondiente (generar, entrenar, agrupar) o actualizar el README."""
import csv
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

import main
from actividad3.supervisado import CLASES, SEMILLA, _cargar, dir_resultados, preparar, ruta_modelo
from actividad4 import no_supervisado
from aprendizaje.arbol import ArbolDecision
from aprendizaje.datos import (COLUMNAS_ESTACIONES, DIAS_SEMANA, HORAS, RUTA_ESTACIONES, RUTA_REAL, RUTA_VALIDACIONES,
                               atributos_estaciones, cargar_dataset, generar_dataset, tipo_de_dia)
from aprendizaje.datos_reales import CODIGOS_ESTACION
from aprendizaje.evaluacion import calcular_metricas, division_estratificada
from aprendizaje.salida import pct
from sistema.red import RedTransporte
from tests.test_main import capturar

DIR_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIEMPO = re.compile(r"\d+\.\d+ ms")          # el tiempo de cada búsqueda cambia en cada ejecución
BORDES = "│╭╮╰╯┌┐└┘─ "                       # rich usa esquinas rectas cuando la salida no es una terminal


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def bloque_del_readme(marca):
    """Líneas del primer bloque de código del README que aparece después de la línea con 'marca'."""
    lineas = leer(os.path.join(DIR_RAIZ, "README.md")).splitlines()
    inicio = next(i for i, linea in enumerate(lineas) if marca in linea)
    apertura = next(i for i in range(inicio, len(lineas)) if lineas[i].startswith("```"))
    cierre = next(i for i in range(apertura + 1, len(lineas)) if lineas[i].startswith("```"))
    return lineas[apertura + 1:cierre]


def contenido(lineas):
    """Líneas de texto sin los bordes de los paneles y reglas de rich, y con el tiempo enmascarado."""
    limpias = (TIEMPO.sub("… ms", linea.strip().strip(BORDES)) for linea in lineas)
    return [linea for linea in limpias if linea]


def linea_con(lineas, marca):
    return next(linea.strip().strip(BORDES) for linea in lineas if linea.startswith(marca))


def filas_de_tabla(lineas):
    """Celdas de cada fila de una tabla de rich, sin la última columna (ms)."""
    return [[c.strip() for c in linea.strip().strip("│").split("│")][:-1] for linea in lineas if linea.startswith("│")]


def texto_desde(lineas, marca):
    """Texto desde la línea que empieza con 'marca' hasta el final, sin importar dónde se partió."""
    i = next(i for i, linea in enumerate(lineas) if linea.startswith(marca))
    return " ".join(" ".join(lineas[i:]).split())


class TestEjemplosDelReadme(unittest.TestCase):
    """Las salidas que muestra el README son las que produce el programa hoy."""

    def test_ruta_portal_el_dorado_museo_del_oro(self):
        readme = bloque_del_readme("Desde la línea de comandos, la misma ruta da:")
        codigo, texto = capturar(lambda: main.main(["ruta", "Portal El Dorado", "Museo del Oro"]))
        self.assertEqual(codigo, 0)
        self.assertGreater(len(contenido(readme)), 5)     # el bloque del README se encontró y se leyó
        self.assertEqual(contenido(texto.splitlines()), contenido(readme))

    def test_comparacion_escuela_militar_u_nacional(self):
        readme = bloque_del_readme("Se incluyen cuatro estrategias para comparar")
        codigo, texto = capturar(lambda: main.main(["comparar", "Escuela Militar", "U. Nacional"]))
        salida = texto.splitlines()
        self.assertEqual(codigo, 0)
        self.assertEqual(len(filas_de_tabla(readme)), 5)  # encabezado + 4 algoritmos
        self.assertEqual(filas_de_tabla(salida), filas_de_tabla(readme))
        for marca in ("Comparación de estrategias:", "Criterio:"):
            self.assertEqual(linea_con(salida, marca), linea_con(readme, marca))
        self.assertEqual(texto_desde(salida, "Ruta encontrada por A*:"), texto_desde(readme, "Ruta encontrada por A*:"))

    def test_explicacion_de_un_transbordo(self):
        readme = bloque_del_readme("Cada hecho derivado guarda su justificación")
        esperadas = [linea for linea in readme[1:] if linea != "..."]
        explicacion = RedTransporte().kb.explicar(("transbordo", ("Ricaurte", "E", "F"))).splitlines()
        self.assertTrue(esperadas)
        self.assertEqual(explicacion[:len(esperadas)], esperadas)


class TestDatosPublicados(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()

    def test_la_muestra_se_regenera_identica(self):
        """'python -m actividad3 generar' con sus valores por defecto produce exactamente el CSV publicado."""
        self.assertEqual(generar_dataset(self.red, dias=28, semilla=42), cargar_dataset(RUTA_VALIDACIONES))

    def test_catalogo_de_estaciones_al_dia(self):
        with open(RUTA_ESTACIONES, encoding="utf-8", newline="") as f:
            publicado = list(csv.DictReader(f))
        atributos = atributos_estaciones(self.red)
        self.assertEqual(publicado, [{c: str(atributos[e][c]) for c in COLUMNAS_ESTACIONES} for e in sorted(atributos)])

    def test_contrato_de_los_datos_reales(self):
        filas = cargar_dataset(RUTA_REAL)
        estaciones = sorted({f["estacion"] for f in filas})
        fechas = sorted({f["fecha"] for f in filas})
        self.assertEqual(estaciones, sorted(e for e, codigos in CODIGOS_ESTACION.items() if codigos))
        self.assertEqual((fechas[0], fechas[-1], len(fechas)), ("2026-03-02", "2026-03-29", 28))
        self.assertEqual(len({(f["estacion"], f["fecha"], f["hora"]) for f in filas}), len(filas))   # sin duplicados
        self.assertEqual(len(filas), len(estaciones) * len(fechas) * len(HORAS))                    # malla completa
        calendario = {d: (tipo_de_dia(date.fromisoformat(d)), DIAS_SEMANA[date.fromisoformat(d).weekday()])
                      for d in fechas}
        self.assertEqual([f for f in filas if (f["tipo_dia"], f["dia_semana"]) != calendario[f["fecha"]]], [])
        self.assertEqual([f for f in filas if f["entradas"] < 0 or f["salidas"] < 0 or f["hora"] not in HORAS], [])
        lluvia = {}
        for f in filas:     # la lluvia es de toda la ciudad: la misma en cada estación a la misma hora
            lluvia.setdefault((f["fecha"], f["hora"]), set()).add(f["lluvia"])
        self.assertEqual({k: v for k, v in lluvia.items() if len(v) != 1 or not v <= {"si", "no"}}, {})


class TestResultadosPublicados(unittest.TestCase):
    def test_el_arbol_guardado_reproduce_su_reporte(self):
        red = RedTransporte()
        for datos in ("real", "muestra"):
            with self.subTest(datos=datos):
                directorio = dir_resultados(datos)
                arbol = ArbolDecision.desde_json(leer(ruta_modelo(datos)))
                X, y = preparar(_cargar(red, datos))
                _, prueba = division_estratificada(y, 0.3, SEMILLA)
                m = calcular_metricas([y[i] for i in prueba], arbol.predecir_lote([X[i] for i in prueba]), CLASES)
                self.assertIn(f"| Árbol de decisión (prof. {arbol.profundidad_max}) | {pct(m.exactitud)} | "
                              f"{m.f1_macro:.3f} |", leer(os.path.join(directorio, "reporte.md")))
                reglas = arbol.extraer_reglas()
                lineas = leer(os.path.join(directorio, "reglas.txt")).splitlines()
                self.assertIn(f"{len(reglas)} reglas", lineas[0])
                self.assertEqual(lineas[1:], [str(r) for r in reglas])
                self.assertEqual(leer(os.path.join(directorio, "arbol.txt")), arbol.a_texto() + "\n")

    def test_el_agrupamiento_publicado_se_reproduce(self):
        """'python -m actividad4 agrupar' en una carpeta temporal regenera los mismos 9 archivos publicados."""
        publicados = no_supervisado.DIR_ACTIVIDAD
        archivos = {"perfiles.kb", "asignacion.csv", "reporte.md", "codo.svg", "silueta.svg", "dendrograma.svg",
                    "perfiles_entradas.svg", "perfiles_salidas.svg", "mapa_clusters.svg"}
        for argumentos in (["agrupar"], ["agrupar", "-k", "5"], ["agrupar", "--datos", "muestra"]):
            with self.subTest(argumentos=argumentos), tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(no_supervisado, "DIR_ACTIVIDAD", tmp):
                    codigo, _ = capturar(lambda: no_supervisado.main(argumentos))
                self.assertEqual(codigo, 0)
                generados = [os.path.relpath(os.path.join(carpeta, nombre), tmp)
                             for carpeta, _, nombres in os.walk(tmp) for nombre in nombres]
                self.assertEqual({os.path.basename(g) for g in generados}, archivos)
                for relativa in generados:
                    nuevo, publicado = leer(os.path.join(tmp, relativa)), leer(os.path.join(publicados, relativa))
                    if relativa.endswith("reporte.md"):    # la fecha de generación sí cambia
                        nuevo, publicado = (re.sub(r"Generado el \d{4}-\d{2}-\d{2}", "", t) for t in (nuevo, publicado))
                    self.assertEqual(nuevo, publicado, relativa)


CODIGO_DETERMINISMO = """
import hashlib
from aprendizaje.datos import generar_dataset
from sistema.busqueda import ALGORITMOS, buscar_ruta
from sistema.red import RedTransporte

red = RedTransporte()
partes = [repr(red.kb.consultar("transbordo(E, T1, T2)")), red.kb.explicar(("transbordo", ("Ricaurte", "E", "F"))),
          repr(red.estadisticas)]
for origen, destino in [("Portal 80", "Portal Américas"), ("Escuela Militar", "U. Nacional"),
                        ("Portal Norte", "Museo del Oro")]:
    for algoritmo in ALGORITMOS:
        r = buscar_ruta(red, origen, destino, algoritmo)
        partes.append(repr((r.estaciones_ruta, r.nodos_expandidos, r.nodos_generados, r.max_frontera, r.costo)))
partes.append(repr(generar_dataset(red, dias=1, semilla=3)))
print(hashlib.sha256("\\n".join(partes).encode("utf-8")).hexdigest())
"""


class TestDeterminismo(unittest.TestCase):
    def test_resultados_independientes_del_hash_de_python(self):
        """Python cambia en cada ejecución el orden de los conjuntos de cadenas (PYTHONHASHSEED): ninguna
        consulta, explicación, ruta, conteo de nodos ni dato generado debe depender de ese orden."""
        huellas = set()
        for semilla in ("0", "1", "12345"):
            proceso = subprocess.run([sys.executable, "-c", CODIGO_DETERMINISMO], cwd=DIR_RAIZ, capture_output=True,
                                     text=True, timeout=120, env={**os.environ, "PYTHONHASHSEED": semilla})
            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            huellas.add(proceso.stdout.strip())
        self.assertEqual(len(huellas), 1)


if __name__ == "__main__":
    unittest.main()
