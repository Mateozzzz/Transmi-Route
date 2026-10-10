"""Pruebas avanzadas de los datos (Actividades 3 y 4): calendario de festivos, modelo de la
muestra sintética, lector de XLSX e importación de los datos reales sin conexión."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from collections import Counter
from datetime import date
from unittest import mock
from xml.sax.saxutils import escape

from aprendizaje import datos_reales
from aprendizaje.datos import (_FESTIVOS_AL_LUNES, _FESTIVOS_FIJOS, FACTOR_TIPO_DIA, FACTOR_TIPO_DIA_OCIO, HORAS,
                               VOCACIONES, _pascua, atributos_estaciones, cargar_dataset, festivos_colombia,
                               generar_dataset, perfil_horario, tipo_de_dia, vocacion_latente)
from aprendizaje.datos_reales import (_columna, _fecha_de_columna, _hora_de_intervalo, filas_xlsx, importar,
                                      lluvia_por_hora, obtener)
from sistema.red import RedTransporte
from tests.test_datos_reales import ENTRADAS, SALIDAS, _letra, escribir_xlsx


class TestCalendario(unittest.TestCase):
    def test_pascua_en_fechas_conocidas(self):
        conocidas = [date(2000, 4, 23), date(2008, 3, 23), date(2011, 4, 24), date(2019, 4, 21), date(2024, 3, 31),
                     date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28), date(2038, 4, 25),
                     date(2285, 3, 22)]                     # 2285: la más temprana posible
        for fecha in conocidas:
            with self.subTest(anio=fecha.year):
                self.assertEqual(_pascua(fecha.year), fecha)

    def test_pascua_siempre_es_domingo_entre_el_22_de_marzo_y_el_25_de_abril(self):
        for anio in range(1583, 2401):          # todo el calendario gregoriano hasta 2400
            with self.subTest(anio=anio):
                pascua = _pascua(anio)
                self.assertEqual(pascua.weekday(), 6)
                self.assertTrue(date(anio, 3, 22) <= pascua <= date(anio, 4, 25))

    def test_festivos_trasladables_caen_en_lunes(self):
        """Ley 51 de 1983: los festivos se pasan al lunes siguiente, salvo los fijos y la Semana Santa."""
        fijos = {nombre: (m, d) for (m, d), nombre in _FESTIVOS_FIJOS.items()}
        al_lunes = {nombre: (m, d) for (m, d), nombre in _FESTIVOS_AL_LUNES.items()}
        for anio in range(1984, 2101):
            festivos, pascua = festivos_colombia(anio), _pascua(anio)
            with self.subTest(anio=anio):
                self.assertIn(len(festivos), (17, 18))   # 17 cuando dos festivos caen el mismo día
                for fecha, nombre in festivos.items():
                    if nombre in fijos:
                        self.assertEqual((fecha.month, fecha.day), fijos[nombre])
                    elif nombre in ("Jueves Santo", "Viernes Santo"):
                        self.assertEqual((pascua - fecha).days, 3 if nombre == "Jueves Santo" else 2)
                    else:
                        self.assertEqual(fecha.weekday(), 0, nombre)
                        if nombre in al_lunes:
                            self.assertIn((fecha - date(anio, *al_lunes[nombre])).days, range(7))

    def test_festivos_que_coinciden_cuentan_una_vez(self):
        """En 2025, San Pedro y San Pablo (29 de junio, domingo) y Sagrado Corazón caen el lunes 30 de junio."""
        festivos = festivos_colombia(2025)
        self.assertEqual(len(festivos), 17)
        self.assertEqual(festivos[date(2025, 6, 30)], "San Pedro y San Pablo")
        self.assertEqual(_pascua(2025).toordinal() + 71, date(2025, 6, 30).toordinal())   # Sagrado Corazón

    def test_tipo_de_dia_en_todo_un_anio(self):
        """2026: 52 sábados, 52 domingos y los 18 festivos caen entre semana."""
        conteo = Counter(tipo_de_dia(date.fromordinal(n))
                         for n in range(date(2026, 1, 1).toordinal(), date(2027, 1, 1).toordinal()))
        self.assertEqual(conteo, {"habil": 365 - 52 - 52 - 18, "sabado": 52, "domingo_festivo": 52 + 18})


class TestModeloDeLaMuestra(unittest.TestCase):
    """Los datos generados reflejan los supuestos documentados del modelo de la muestra sintética."""

    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        cls.atributos = atributos_estaciones(cls.red)
        cls.filas = generar_dataset(cls.red, dias=28, semilla=42)

    def test_perfiles_horarios_suman_uno(self):
        for vocacion in VOCACIONES:
            for tipo in FACTOR_TIPO_DIA:
                for sentido in ("entradas", "salidas"):
                    with self.subTest(vocacion=vocacion, tipo=tipo, sentido=sentido):
                        perfil = perfil_horario(vocacion, tipo, sentido)
                        self.assertEqual(len(perfil), len(HORAS))
                        self.assertAlmostEqual(sum(perfil), 1.0)
                        self.assertTrue(all(p > 0 for p in perfil))

    def test_factores_de_fin_de_semana_se_reflejan_en_los_datos(self):
        """Entradas de un sábado o domingo promedio frente a las de un día hábil promedio."""
        dias = Counter(tipo for _, tipo in {(f["fecha"], f["tipo_dia"]) for f in self.filas})
        totales = Counter()
        for f in self.filas:
            ocio = vocacion_latente(f["estacion"], self.atributos[f["estacion"]]) == "educativa_ocio"
            totales[(ocio, f["tipo_dia"])] += f["entradas"]
        for ocio, factores in ((False, FACTOR_TIPO_DIA), (True, FACTOR_TIPO_DIA_OCIO)):
            habil = totales[(ocio, "habil")] / dias["habil"]
            for tipo in ("sabado", "domingo_festivo"):
                with self.subTest(educativa_ocio=ocio, tipo=tipo):
                    self.assertAlmostEqual(totales[(ocio, tipo)] / dias[tipo] / habil, factores[tipo], delta=0.03)

    def test_la_lluvia_es_de_toda_la_ciudad_y_mas_frecuente_en_la_tarde(self):
        lluvia = {}
        for f in self.filas:
            lluvia.setdefault((f["fecha"], f["hora"]), set()).add(f["lluvia"])
        self.assertTrue(all(len(v) == 1 for v in lluvia.values()))
        tarde = [v == {"si"} for (_, hora), v in lluvia.items() if 13 <= hora <= 18]
        resto = [v == {"si"} for (_, hora), v in lluvia.items() if not 13 <= hora <= 18]
        self.assertAlmostEqual(sum(tarde) / len(tarde), 0.40, delta=0.1)    # probabilidades del modelo
        self.assertAlmostEqual(sum(resto) / len(resto), 0.06, delta=0.04)

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            generar_dataset(self.red, dias=0)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "importar"):
            cargar_dataset(os.path.join(tmp, "no_existe.csv"))


NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def xlsx_con_hojas(ruta, hojas):
    """XLSX con varias hojas; cada una se da como el XML de sus filas."""
    with zipfile.ZipFile(ruta, "w") as z:
        for nombre, filas in hojas.items():
            z.writestr(f"xl/worksheets/{nombre}.xml",
                       f'<worksheet xmlns="{NS}"><sheetData>{filas}</sheetData></worksheet>')


def fila_xml(n, valores, referencias=True):
    """Fila de textos en línea; sin referencias, cada celda toma la columna siguiente a la anterior."""
    celdas = []
    for j, v in enumerate(valores):
        ref = f' r="{_letra(j)}{n}"' if referencias else ""
        celdas.append(f'<c{ref} t="inlineStr"><is><t>{escape(v)}</t></is></c>')
    return f'<row r="{n}">' + "".join(celdas) + "</row>"


class TestLectorXlsx(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def test_columna_ida_y_vuelta(self):
        self.assertEqual([i for i in range(20000) if _columna(f"{_letra(i)}7") != i], [])
        self.assertEqual(_columna("XFD1048576"), 16383)     # última celda de una hoja de Excel

    def test_cuartos_de_hora_con_15_cifras_significativas(self):
        """Excel guarda la hora como fracción del día con 15 cifras: las 11:00 son 0.458333333333333,
        un poco menos que 11/24, y aun así deben leerse como la hora 11."""
        for minuto in range(0, 24 * 60, 15):
            with self.subTest(minuto=minuto):
                self.assertEqual(_hora_de_intervalo(f"{minuto / 1440:.15g}"), minuto // 60)
                self.assertEqual(_hora_de_intervalo(f"{minuto // 60:02d}:{minuto % 60:02d}:00"), minuto // 60)

    def test_intervalos_y_fechas_invalidos(self):
        for texto in ("1", "24:00:00", "-0.1", "abc", ""):
            with self.subTest(intervalo=texto):
                self.assertIsNone(_hora_de_intervalo(texto))
        for texto in ("46083.5", "123456", "Total general", "2026-03-02", ""):
            with self.subTest(fecha=texto):
                self.assertIsNone(_fecha_de_columna(texto))
        for texto in ("46083", "46083.0", "_2026_03_02", "2026_03_02"):
            with self.subTest(fecha=texto):
                self.assertEqual(_fecha_de_columna(texto), date(2026, 3, 2))

    def test_elige_la_primera_hoja_con_encabezado_en_orden_numerico(self):
        """sheet2 va antes que sheet10: en orden alfabético sería al revés."""
        ruta = os.path.join(self.tmp, "hojas.xlsx")
        encabezado = ["Estación", "Intervalo", "46083"]
        xlsx_con_hojas(ruta, {"sheet1": fila_xml(1, ["Resumen sin encabezado"]),
                              "sheet10": fila_xml(1, encabezado) + fila_xml(2, ["(00010) Diez", "0.25", "1"]),
                              "sheet2": fila_xml(1, encabezado) + fila_xml(2, ["(00002) Dos", "0.25", "1"])})
        self.assertEqual([f[0] for f in filas_xlsx(ruta)], ["Estación", "(00002) Dos"])

    def test_celdas_sin_referencia_toman_la_posicion(self):
        ruta = os.path.join(self.tmp, "sin_r.xlsx")
        xlsx_con_hojas(ruta, {"sheet1": fila_xml(1, ["Estación", "Intervalo"], referencias=False)
                                        + fila_xml(2, ["(02000) Portal Norte", "06:00:00"], referencias=False)})
        self.assertEqual(list(filas_xlsx(ruta)),
                         [{0: "Estación", 1: "Intervalo"}, {0: "(02000) Portal Norte", 1: "06:00:00"}])

    def test_archivo_que_no_es_xlsx(self):
        ruta = os.path.join(self.tmp, "falso.xlsx")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("fecha,hora\n")
        with self.assertRaisesRegex(ValueError, "no es un archivo XLSX válido"):
            list(filas_xlsx(ruta))


class Interrumpida(io.BytesIO):
    """Respuesta HTTP que se corta a mitad de la descarga."""

    def read(self, *args):
        raise OSError("conexión interrumpida")

    readinto = read


class TestImportacionSinConexion(unittest.TestCase):
    """Descargas, caché y conversión de los datos reales sin tocar la red ni datos/crudos/."""

    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.crudos = os.path.join(self.tmp, "crudos")
        parche = mock.patch.object(datos_reales, "DIR_CRUDOS", self.crudos)
        parche.start()
        self.addCleanup(parche.stop)

    def escribir_lluvia(self, desde, hasta, precipitacion):
        """Deja en la caché la respuesta de Open-Meteo que lluvia_por_hora buscaría en la red."""
        os.makedirs(self.crudos, exist_ok=True)
        horas = sorted(precipitacion)
        with open(os.path.join(self.crudos, f"lluvia_open-meteo_{desde}_{hasta}.json"), "w", encoding="utf-8") as f:
            json.dump({"hourly": {"time": horas, "precipitation": [precipitacion[h] for h in horas]}}, f)

    def test_obtener_descarga_una_sola_vez(self):
        avisos = []
        url = "https://ejemplo.org/datos/reporte%20marzo.xlsx"
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"contenido")) as urlopen:
            primera = obtener(url, aviso=avisos.append)
            segunda = obtener(url, aviso=avisos.append)
        self.assertEqual(primera, os.path.join(self.crudos, "reporte marzo.xlsx"))
        self.assertEqual(segunda, primera)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(avisos, ["Descargando reporte marzo.xlsx ..."])
        with open(primera, "rb") as f:
            self.assertEqual(f.read(), b"contenido")
        self.assertEqual(obtener(primera), primera)          # un archivo local se usa tal cual
        with self.assertRaisesRegex(ValueError, "No existe el archivo"):
            obtener(os.path.join(self.tmp, "no_existe.xlsx"))

    def test_descarga_interrumpida_no_deja_archivo_parcial(self):
        with mock.patch("urllib.request.urlopen", return_value=Interrumpida()):
            with self.assertRaisesRegex(ValueError, "--entradas"):
                obtener("https://ejemplo.org/reporte.xlsx", aviso=lambda texto: None)
        self.assertEqual(os.listdir(self.crudos), [])

    def test_lluvia_por_hora_usa_el_umbral(self):
        dia = date(2026, 3, 2)
        self.escribir_lluvia(dia, dia, {"2026-03-02T06:00": 0.2, "2026-03-02T07:00": 0.19, "2026-03-02T08:00": None})
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("sin red")):
            lluvia = lluvia_por_hora(dia, dia, 4.604, -74.0775, aviso=lambda texto: None)
        self.assertEqual(lluvia, {(dia, 6): True, (dia, 7): False, (dia, 8): False})

    def test_importar_de_principio_a_fin(self):
        entradas, salidas = os.path.join(self.tmp, "entradas.xlsx"), os.path.join(self.tmp, "salidas.xlsx")
        escribir_xlsx(entradas, ENTRADAS, compartidas=True)
        escribir_xlsx(salidas, SALIDAS)
        desde, hasta = date(2026, 3, 2), date(2026, 3, 29)
        self.escribir_lluvia(desde, hasta, {"2026-03-02T18:00": 1.5, "2026-03-23T06:00": 0.1})
        ruta, avisos = os.path.join(self.tmp, "real.csv"), []
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("sin red")):
            r = importar(entradas, salidas, desde, hasta, red=self.red, ruta=ruta, aviso=avisos.append)
        self.assertEqual(avisos, [])
        self.assertEqual((r.filas, r.estaciones), (2 * len(HORAS), ["Portal Norte"]))
        self.assertIn("Ricaurte (07111, salidas)", r.codigos_ausentes)   # sin datos en un archivo: se excluye
        self.assertEqual(r.sin_datos, ["Calle 19", "Calle 63", "Calle 72", "Patio Bonito", "Tercer Milenio"])
        self.assertEqual(r.fechas, [date(2026, 3, 2), date(2026, 3, 23)])
        self.assertEqual(r.entradas_sistema_por_dia, {date(2026, 3, 2): 1144, date(2026, 3, 23): 1102})
        self.assertAlmostEqual(r.horas_con_lluvia, 1 / 38)
        filas = {(f["fecha"], f["hora"]): f for f in cargar_dataset(ruta)}
        self.assertEqual(len(filas), 38)
        self.assertEqual(filas[("2026-03-02", 6)]["entradas"], 35)
        self.assertEqual((filas[("2026-03-02", 18)]["salidas"], filas[("2026-03-02", 18)]["lluvia"]), (10, "si"))


if __name__ == "__main__":
    unittest.main()
