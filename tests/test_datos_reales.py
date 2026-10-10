"""Pruebas del conversor de datos reales de TRANSMILENIO (sin conexión: XLSX mínimos en un directorio temporal)."""
import os
import re
import tempfile
import unittest
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from aprendizaje.datos import COLUMNAS_VALIDACIONES
from aprendizaje.datos_reales import CODIGOS_ESTACION, convertir, filas_xlsx, leer_intervalos
from sistema.red import RedTransporte

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _letra(i):
    letras = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def escribir_xlsx(ruta, filas, compartidas=False):
    """XLSX mínimo de una hoja. Los números van como valores; los textos como
    cadenas compartidas (como el reporte de entradas) o en línea (como el de salidas)."""
    cadenas = []

    def celda(ref, v):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        if compartidas:
            if v not in cadenas:
                cadenas.append(v)
            return f'<c r="{ref}" t="s"><v>{cadenas.index(v)}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'

    xml = "".join(f'<row r="{n}">' + "".join(celda(f"{_letra(j)}{n}", v) for j, v in enumerate(fila) if v != "")
                  + "</row>" for n, fila in enumerate(filas, 1))
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{_NS}"><sheetData>{xml}</sheetData></worksheet>')
        if compartidas:
            z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{_NS}">'
                       + "".join(f"<si><t>{escape(s)}</t></si>" for s in cadenas) + "</sst>")


# Reporte de entradas: fechas como número de serie de Excel (46083 = 2026-03-02,
# 46104 = 2026-03-23, festivo de San José), intervalo como fracción del día,
# una ruta dual y la fila de total general que no se debe sumar.
ENTRADAS = [
    ["Reporte Validaciones por Intervalo Estaciones Troncales y Rutas Duales - Tarjeta Tullave"],
    ["", "Periodo Validaciones:", "", "al 31 de Marzo 2026"],
    ["Fase", "Línea", "Estación", "Acceso de Estación", "Intervalo", 46083, 46104, "Total general"],
    ["Troncal", "(33) Zona B AutoNorte", "(02000) Portal Norte - Unicervantes", "(01) Norte", 0.25, 10, 1, 11],
    ["Troncal", "(33) Zona B AutoNorte", "(02000) Portal Norte - Unicervantes", "(01) Norte", 0.260416666666667, 20, 2, 22],
    ["Troncal", "(33) Zona B AutoNorte", "(02000) Portal Norte - Unicervantes", "(02) Sur", 0.25, 5, 0, 5],
    ["Troncal", "(33) Zona B AutoNorte", "(02000) Portal Norte - Unicervantes", "(02) Sur", 0.125, 99, 99, 198],
    ["Troncal", "(38) Zona E NQS Central", "(07111) NQS - RICAURTE", "(01) Peatonal", 0.75, 7, 0, 7],
    ["Troncal", "(39) Zona F Calle 13", "(12003) Ricaurte", "(01) Peatonal", 0.770833333333333, 3, 0, 3],
    ["Dual", "(10006) M84-C84", "(12387) MC84_V5", "(0) (Unknown)", 0.25, 1000, 1000, 2000],
    [],
    ["Total general", "Total general", "Total general", "Total general", "Total general", 1144, 1102, 2246],
]
# Reporte de salidas: cadenas en línea, fechas "_AAAA_MM_DD", intervalo "HH:MM:SS"
SALIDAS = [
    ["Reporte de Salidas Fase III"],
    ["Periodo", "Reporte de 20260401"],
    ["Linea", "Estacion", "Acceso_Estacion", "Intervalo", "_2026_03_02", "_2026_03_23", "total_general"],
    ["(33)Zona B AutoNorte", "(02000)Portal Norte - Unicervantes", "(01) Norte", "18:00:00", "4", "1", "5"],
    ["(33)Zona B AutoNorte", "(02000)Portal Norte - Unicervantes", "(01) Norte", "18:45:00", "6", "0", "6"],
    ["(39)Zona F Calle 13", "(12003)Ricaurte", "(01) Peatonal", "06:30:00", "2", "X", "2"],
]


class TestConversor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ruta_ent = os.path.join(cls.tmp.name, "entradas.xlsx")
        cls.ruta_sal = os.path.join(cls.tmp.name, "salidas.xlsx")
        escribir_xlsx(cls.ruta_ent, ENTRADAS, compartidas=True)
        escribir_xlsx(cls.ruta_sal, SALIDAS)
        cls.ent = leer_intervalos(cls.ruta_ent)
        cls.sal = leer_intervalos(cls.ruta_sal)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_suma_accesos_e_intervalos_de_la_hora(self):
        self.assertEqual(self.ent.conteos[("02000", date(2026, 3, 2), 6)], 35)   # 10 + 20 + 5
        self.assertEqual(self.ent.conteos[("02000", date(2026, 3, 23), 6)], 3)
        self.assertEqual(self.ent.conteos[("02000", date(2026, 3, 2), 3)], 99)   # se lee; convertir la descarta
        self.assertEqual(self.sal.conteos[("02000", date(2026, 3, 2), 18)], 10)
        self.assertNotIn(("12003", date(2026, 3, 23), 6), self.sal.conteos)      # celda "X"

    def test_ignora_filas_sin_codigo_y_total_general(self):
        self.assertEqual(self.ent.total_por_dia[date(2026, 3, 2)], 1144)       # sin la fila de total
        self.assertEqual(self.ent.nombres["02000"], "Portal Norte - Unicervantes")
        self.assertEqual(self.sal.nombres["12003"], "Ricaurte")

    def test_convertir_al_formato_de_la_muestra(self):
        codigos = {"Portal Norte": ("02000",), "Ricaurte": ("07111", "12003"), "Calle 72": ()}
        lluvia = {(date(2026, 3, 2), 18): True}
        filas = convertir(self.ent.conteos, self.sal.conteos, lluvia, date(2026, 3, 1), date(2026, 3, 31), codigos)
        self.assertEqual(len(filas), 2 * 2 * 19)      # 2 estaciones con código × 2 días × 19 horas
        self.assertEqual(list(filas[0]), COLUMNAS_VALIDACIONES)
        f = {(r["estacion"], r["fecha"], r["hora"]): r for r in filas}
        self.assertEqual(f[("Portal Norte", "2026-03-02", 6)]["entradas"], 35)
        self.assertEqual(f[("Portal Norte", "2026-03-02", 18)]["salidas"], 10)
        self.assertEqual(f[("Ricaurte", "2026-03-02", 18)]["entradas"], 10)    # 07111 + 12003
        self.assertEqual(f[("Ricaurte", "2026-03-02", 6)]["salidas"], 2)
        self.assertEqual(f[("Portal Norte", "2026-03-02", 18)]["lluvia"], "si")
        self.assertEqual(f[("Portal Norte", "2026-03-02", 17)]["lluvia"], "no")
        self.assertEqual(f[("Portal Norte", "2026-03-02", 6)]["dia_semana"], "lunes")
        self.assertEqual(f[("Portal Norte", "2026-03-23", 6)]["tipo_dia"], "domingo_festivo")
        self.assertNotIn(("Calle 72", "2026-03-02", 6), f)
        self.assertNotIn(("Portal Norte", "2026-03-02", 3), f)                    # fuera de HORAS

    def test_ventana_de_fechas(self):
        filas = convertir(self.ent.conteos, self.sal.conteos, {}, date(2026, 3, 2), date(2026, 3, 2),
                          {"Portal Norte": ("02000",)})
        self.assertEqual({r["fecha"] for r in filas}, {"2026-03-02"})
        with self.assertRaises(ValueError):
            convertir(self.ent.conteos, self.sal.conteos, {}, date(2026, 4, 1), date(2026, 4, 30))

    def test_archivo_sin_encabezado(self):
        ruta = os.path.join(self.tmp.name, "otro.xlsx")
        escribir_xlsx(ruta, [["Columna", "Otra"], ["1", "2"]])
        with self.assertRaises(ValueError):
            list(filas_xlsx(ruta))


class TestTablaDeCodigos(unittest.TestCase):
    def test_cubre_exactamente_la_base_de_conocimiento(self):
        self.assertEqual(set(CODIGOS_ESTACION), set(RedTransporte().estaciones))

    def test_codigos_validos_y_sin_repetir(self):
        todos = [c for cods in CODIGOS_ESTACION.values() for c in cods]
        self.assertTrue(all(re.fullmatch(r"\d{5}", c) for c in todos))
        self.assertEqual(len(todos), len(set(todos)))
        self.assertEqual(sum(1 for cods in CODIGOS_ESTACION.values() if cods), 80)


if __name__ == "__main__":
    unittest.main()
