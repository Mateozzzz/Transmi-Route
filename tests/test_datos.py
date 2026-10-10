"""Pruebas del dataset de muestra (afluencia por estación y hora)."""
import os
import tempfile
import unittest
from collections import Counter
from datetime import date

from actividad3.supervisado import CLASES, nivel_demanda
from aprendizaje.datos import (COLUMNAS_VALIDACIONES, HORAS, atributos_estaciones, cargar_dataset,
                               festivos_colombia, generar_dataset, guardar_csv, unir_atributos, vocacion_latente)
from sistema.red import RedTransporte


class TestDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.red = RedTransporte()
        cls.atributos = atributos_estaciones(cls.red)
        cls.filas = generar_dataset(cls.red, dias=28, semilla=42)

    def test_misma_semilla_mismos_datos(self):
        a = generar_dataset(self.red, dias=2, semilla=7)
        b = generar_dataset(self.red, dias=2, semilla=7)
        c = generar_dataset(self.red, dias=2, semilla=8)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_todas_las_estaciones_y_horas(self):
        n = len(self.red.estaciones)
        self.assertEqual(len(self.filas), n * len(HORAS) * 28)
        self.assertEqual({f["estacion"] for f in self.filas}, set(self.red.estaciones))
        self.assertEqual({f["hora"] for f in self.filas}, set(HORAS))
        self.assertEqual(set(self.filas[0]), set(COLUMNAS_VALIDACIONES))

    def test_conteos_no_negativos(self):
        self.assertTrue(all(f["entradas"] >= 0 and f["salidas"] >= 0 for f in self.filas))

    def test_atributos_derivados_de_la_base_de_conocimiento(self):
        a = self.atributos
        self.assertEqual(a["Portal Norte"]["es_portal"], "si")
        self.assertEqual(a["Calle 45"]["es_portal"], "no")
        self.assertEqual(a["Ricaurte"]["num_troncales"], 2)
        self.assertEqual(a["Ricaurte"]["es_integracion"], "si")
        self.assertEqual(a["Av. Jiménez"]["troncales"], "A|F|J")
        self.assertEqual(a["Av. Jiménez"]["distancia_centro_km"], 0)
        self.assertGreater(a["Portal Norte"]["distancia_centro_km"], 15)

    def test_tipo_de_dia_y_festivo(self):
        tipo = {f["fecha"]: f["tipo_dia"] for f in self.filas}
        self.assertEqual(tipo["2026-03-02"], "habil")          # lunes
        self.assertEqual(tipo["2026-03-23"], "domingo_festivo")  # San José (lunes festivo)
        self.assertEqual(tipo["2026-03-28"], "sabado")
        self.assertEqual(tipo["2026-03-29"], "domingo_festivo")
        self.assertEqual(Counter(tipo.values()), {"habil": 19, "sabado": 4, "domingo_festivo": 5})

    def test_festivos_colombia(self):
        f2026 = festivos_colombia(2026)
        # Los festivos del primer semestre que antes estaban escritos a mano
        anteriores = {date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3),
                      date(2026, 5, 1), date(2026, 5, 18), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 29)}
        self.assertTrue(anteriores <= set(f2026))
        self.assertEqual(len(f2026), 18)
        # 2025: Pascua el 20 de abril; San José, Asunción y Día de la Raza pasan al lunes
        for d in (date(2025, 3, 24), date(2025, 4, 17), date(2025, 4, 18), date(2025, 6, 2), date(2025, 6, 23),
                  date(2025, 8, 18), date(2025, 10, 13), date(2025, 11, 3), date(2025, 11, 17)):
            self.assertIn(d, festivos_colombia(2025))

    def test_las_tres_clases_aparecen(self):
        conteo = Counter(nivel_demanda(f["entradas"]) for f in self.filas)
        self.assertEqual(set(conteo), set(CLASES))
        self.assertGreater(min(conteo.values()) / len(self.filas), 0.05)

    def test_patron_residencial_y_de_empleo(self):
        """Portal Norte (residencial) recibe más entradas a las 6 que a las 18; Calle 72 (empleo), al revés."""
        def promedio(est, hora):
            v = [f["entradas"] for f in self.filas
                 if f["estacion"] == est and f["hora"] == hora and f["tipo_dia"] == "habil"]
            return sum(v) / len(v)
        self.assertGreater(promedio("Portal Norte", 6), promedio("Portal Norte", 18))
        self.assertGreater(promedio("Calle 72", 18), promedio("Calle 72", 6))

    def test_vocacion_latente(self):
        a = self.atributos
        self.assertEqual(vocacion_latente("Portal Norte", a["Portal Norte"]), "residencial")
        self.assertEqual(vocacion_latente("Calle 72", a["Calle 72"]), "empleo")
        self.assertEqual(vocacion_latente("U. Nacional", a["U. Nacional"]), "educativa_ocio")

    def test_csv_ida_y_vuelta(self):
        filas = generar_dataset(self.red, dias=1, semilla=1)
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "muestra.csv")
            guardar_csv(filas, ruta, COLUMNAS_VALIDACIONES)
            self.assertEqual(cargar_dataset(ruta), filas)

    def test_union_con_el_catalogo(self):
        unidas = unir_atributos(self.filas[:3], self.atributos)
        self.assertEqual(unidas[0]["latitud"], self.atributos[unidas[0]["estacion"]]["latitud"])
        with self.assertRaises(ValueError):
            unir_atributos([{"estacion": "Inexistente"}], self.atributos)


if __name__ == "__main__":
    unittest.main()
