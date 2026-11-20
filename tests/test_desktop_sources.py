"""Pruebas de regresión contra los cortes reales de 2026.

No se copian fuentes operativas a fixtures ni a Git. Las pruebas se omiten si
las carpetas no existen en el entorno de ejecución.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from metas_etl.cli import run
from metas_etl.normalize import FIELDS, normalize_file

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SOURCES = Path(r"C:\Users\capatino\Desktop\Metas de formación\Metas 2026")
PROJECT_METAS = ROOT / "Metas"

EXPECTED = {
    202604: {"filas": 28, "meta": 31733, "ejecucion": 13974, "delta": (0, 0), "hoja": "30 ABRIL"},
    202608: {"filas": 20, "meta": 31823, "ejecucion": 25379, "delta": (90, 98), "hoja": "Hoja1"},
    202609: {"filas": 20, "meta": 31823, "ejecucion": 28695, "delta": (90, 98), "hoja": "Hoja1"},
    202610: {"filas": 20, "meta": 31823, "ejecucion": 30103, "delta": (90, 57), "hoja": "Hoja1"},
}


@unittest.skipUnless(DESKTOP_SOURCES.is_dir(), "No se encontró la carpeta Desktop\\Metas 2026")
class DesktopSourceTests(unittest.TestCase):
    def test_real_sources_match_expected_contract(self) -> None:
        periods: set[int] = set()
        for path in sorted(DESKTOP_SOURCES.glob("*.xlsx")):
            if "TAYANA" in path.name:
                continue
            facts, info = normalize_file(path)
            period = int(info["periodo"])
            periods.add(period)
            expected = EXPECTED[period]
            with self.subTest(source=path.name, period=period):
                self.assertEqual(info["hoja"], expected["hoja"])
                self.assertEqual(len(facts), expected["filas"])
                self.assertEqual(info["suma_hojas"]["meta"], expected["meta"])
                self.assertEqual(info["suma_hojas"]["ejecucion"], expected["ejecucion"])
                self.assertEqual(
                    (
                        info["diferencia_hojas_vs_total"]["meta"],
                        info["diferencia_hojas_vs_total"]["ejecucion"],
                    ),
                    expected["delta"],
                )
                self.assertEqual(
                    info["estado_conciliacion"],
                    "CUADRA" if expected["delta"] == (0, 0) else "DIFERENCIA_FUENTE",
                )
                for row in facts:
                    self.assertEqual(set(row), set(FIELDS))
        self.assertEqual(periods, set(EXPECTED))

    def test_desktop_batch_omits_tayana_and_writes_monthly_workbooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = run(DESKTOP_SOURCES, root / "data", root / "control", quiet=True)
            self.assertEqual(code, 0)
            outputs = sorted((root / "data").glob("*.xlsx"))
            self.assertEqual(len(outputs), 4)
            self.assertEqual(
                [path.name for path in outputs],
                [
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_04.xlsx",
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_08.xlsx",
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_09.xlsx",
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_10.xlsx",
                ],
            )
            manifest = json.loads(
                (root / "control" / "manifiesto_metas.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["omitidos"]), 1)
            self.assertIn("TAYANA", manifest["omitidos"][0]["fuente"])
            self.assertEqual(manifest["errores"], [])

            for path, period in zip(outputs, (202604, 202608, 202609, 202610)):
                workbook = load_workbook(path, read_only=True, data_only=True)
                try:
                    rows = list(workbook["FactMetas"].iter_rows(values_only=True))
                    period_rows = list(workbook["DimPeriodo"].iter_rows(values_only=True))
                finally:
                    workbook.close()
                self.assertEqual(tuple(rows[0]), FIELDS)
                self.assertEqual(len(rows) - 1, EXPECTED[period]["filas"])
                self.assertEqual(period_rows[1][0], period)


@unittest.skipUnless(PROJECT_METAS.is_dir(), "No se encontró la carpeta Metas del proyecto")
class MayReferenceTests(unittest.TestCase):
    def test_may_workbook_has_canonical_six_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = run(
                PROJECT_METAS / "METAS CENTRO ASTIN - CORTE 31 MAYO 2026.csv",
                root / "data",
                root / "control",
                quiet=True,
            )
            self.assertEqual(code, 0)
            output = next((root / "data").glob("*.xlsx"))
            self.assertEqual(output.name, "Modelo_Normalizado_Metas_Centro_ASTIN_2026_05.xlsx")
            workbook = load_workbook(output, read_only=True, data_only=True)
            try:
                rows = list(workbook["FactMetas"].iter_rows(values_only=True))
            finally:
                workbook.close()
            self.assertEqual(tuple(rows[0]), FIELDS)
            self.assertEqual(len(rows) - 1, 28)
            self.assertEqual(sum(row[4] for row in rows[1:]), 31733)
            self.assertEqual(sum(row[5] for row in rows[1:]), 15505)


if __name__ == "__main__":
    unittest.main()
