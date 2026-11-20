"""Pruebas del libro Excel mensual y de su contrato de serialización."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from metas_etl.catalog import CATEGORIES, INDICATORS, LEVELS
from metas_etl.normalize import FIELDS, normalize_file
from metas_etl.workbook import build_workbook, facts_hash, verify_workbook_bytes


def write_source(path: Path, rows: list[list[object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter=";").writerows(rows)
    return path


def synthetic_may_source(root: Path) -> Path:
    return write_source(
        root / "METAS FORMACION MAYO 2026.csv",
        [
            ["Actualización: 31 de mayo de 2026"],
            ["Metas Formación Profesional Integral", "Meta", "Ejecución", "% Ejecución"],
            ["Tecnólogos Regular - Presencial", "1.523", "1.532", "100,59%"],
            ["Formación Complementaria CampeSENA", "45", "32", "71,11%"],
            ["TOTAL FORMACION COMPLEMENTARIA", "1.568", "1.564", "99,74%"],
            ["TOTAL FORMACION PROFESIONAL INTEGRAL", "1.568", "1.564", "99,74%"],
        ],
    )


class WorkbookContractTests(unittest.TestCase):
    def test_workbook_contains_exact_star_schema_and_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = synthetic_may_source(Path(tmp))
            facts, info = normalize_file(source)
            data = build_workbook(facts, info)

            verify_workbook_bytes(data, facts, info)

            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            try:
                self.assertEqual(
                    workbook.sheetnames,
                    [
                        "FactMetas",
                        "DimCentro",
                        "DimPeriodo",
                        "DimCategoria",
                        "DimNivelFormación",
                        "DimIndicador",
                        "Control",
                    ],
                )
                fact_rows = list(workbook["FactMetas"].iter_rows(values_only=True))
                self.assertEqual(tuple(fact_rows[0]), FIELDS)
                self.assertEqual(len(fact_rows) - 1, 2)
                self.assertNotIn("Porcentaje", fact_rows[0])
                for row in fact_rows[1:]:
                    for value in row:
                        self.assertIsInstance(value, int)

                period_rows = list(workbook["DimPeriodo"].iter_rows(values_only=True))
                self.assertEqual(period_rows[1][0], 202605)
                self.assertEqual(period_rows[1][1:4], (2026, 5, "Mayo"))

                category_rows = list(workbook["DimCategoria"].iter_rows(values_only=True))
                self.assertEqual(len(category_rows), len(CATEGORIES) + 1)
                level_rows = list(workbook["DimNivelFormación"].iter_rows(values_only=True))
                self.assertEqual(len(level_rows), len(LEVELS) + 1)
                indicator_rows = list(workbook["DimIndicador"].iter_rows(values_only=True))
                self.assertEqual(len(indicator_rows), len(INDICATORS) + 1)

                control = {
                    row[0]: row[1]
                    for row in workbook["Control"].iter_rows(min_row=2, values_only=True)
                }
                self.assertEqual(control["IdPeriodo"], 202605)
                self.assertEqual(control["FilasHecho"], 2)
                self.assertEqual(control["HashHecho"], facts_hash(facts))
                self.assertEqual(control["EstadoConciliacion"], "CUADRA")
            finally:
                workbook.close()

    def test_workbook_is_byte_identical_across_builds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = synthetic_may_source(Path(tmp))
            facts, info = normalize_file(source)
            first = build_workbook(facts, info)
            second = build_workbook(facts, info)
            self.assertEqual(first, second)
            self.assertEqual(len(first), len(second))

    def test_workbook_rejects_tampered_fact_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = synthetic_may_source(Path(tmp))
            facts, info = normalize_file(source)
            data = build_workbook(facts, info)
            with self.assertRaises(AssertionError):
                verify_workbook_bytes(data, facts[:-1], info)


class BatchPolicyTests(unittest.TestCase):
    def test_identical_duplicate_period_is_registered_not_reprocessed(self) -> None:
        from metas_etl.cli import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_source(
                root / "fuentes" / "METAS FORMACION AGOSTO 26 - 2026.csv",
                [
                    ["Meta", "100"],
                    ["Ejecución", "80"],
                    ["INDICADOR", "Meta 2026", "Ejecución", "% Ejecución", "Estado"],
                    ["Tecnólogos - Presencial", "100", "80", "80%", "Buena"],
                    ["TOTAL FORMACION COMPLEMENTARIA", "100", "80", "", ""],
                ],
            )
            duplicate = source.with_name("METAS FORMACION AGOSTO 26 - 2026 copia.csv")
            duplicate.write_bytes(source.read_bytes())

            code = run(root / "fuentes", root / "data", root / "control", quiet=True)
            self.assertEqual(code, 0)
            self.assertEqual(len(list((root / "data").glob("*.xlsx"))), 1)
            manifest = json.loads(
                (root / "control" / "manifiesto_metas.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["procesados"]), 1)
            self.assertEqual(len(manifest["duplicados"]), 1)
            self.assertEqual(manifest["duplicados"][0]["motivo"], "Mismo periodo y mismos hechos")

    def test_conflicting_period_fails_by_default(self) -> None:
        from metas_etl.cli import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                ["Meta", "100"],
                ["Ejecución", "80"],
                ["INDICADOR", "Meta 2026", "Ejecución", "% Ejecución", "Estado"],
                ["Tecnólogos - Presencial", "100", "80", "80%", "Buena"],
                ["TOTAL FORMACION COMPLEMENTARIA", "100", "80", "", ""],
            ]
            write_source(root / "fuentes" / "METAS FORMACION AGOSTO 15 - 2026.csv", base)
            variant = [list(row) for row in base]
            variant[3] = ["Tecnólogos - Presencial", "90", "70", "77%", "Buena"]
            write_source(root / "fuentes" / "METAS FORMACION AGOSTO 26 - 2026.csv", variant)

            code = run(root / "fuentes", root / "data", root / "control", quiet=True)
            self.assertEqual(code, 1)
            self.assertEqual(list((root / "data").glob("*.xlsx")), [])
            manifest = json.loads(
                (root / "control" / "manifiesto_metas.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["errores"]), 1)
            self.assertIn("Conflicto de periodo", manifest["errores"][0]["error"])

    def test_latest_policy_selects_newest_cut(self) -> None:
        from metas_etl.cli import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                ["Meta", "100"],
                ["Ejecución", "80"],
                ["INDICADOR", "Meta 2026", "Ejecución", "% Ejecución", "Estado"],
                ["Tecnólogos - Presencial", "100", "80", "80%", "Buena"],
                ["TOTAL FORMACION COMPLEMENTARIA", "100", "80", "", ""],
            ]
            write_source(root / "fuentes" / "METAS FORMACION AGOSTO 15 - 2026.csv", base)
            variant = [list(row) for row in base]
            variant[3] = ["Tecnólogos - Presencial", "90", "70", "77%", "Buena"]
            write_source(root / "fuentes" / "METAS FORMACION AGOSTO 26 - 2026.csv", variant)

            code = run(
                root / "fuentes",
                root / "data",
                root / "control",
                period_policy="latest",
                quiet=True,
            )
            self.assertEqual(code, 0)
            _, info = normalize_file(root / "fuentes" / "METAS FORMACION AGOSTO 26 - 2026.csv")
            self.assertEqual(info["fecha_corte"], "2026-08-26")
            workbook = load_workbook(
                next((root / "data").glob("*.xlsx")), read_only=True, data_only=True
            )
            try:
                rows = list(workbook["FactMetas"].iter_rows(values_only=True))
            finally:
                workbook.close()
            self.assertEqual(rows[1][4], 90)

    def test_strict_fails_on_omitted_source(self) -> None:
        from metas_etl.cli import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_source(root / "fuentes" / "documento_auxiliar.csv", [["sin fecha"], ["sin indicadores"]])
            code = run(root / "fuentes", root / "data", root / "control", quiet=True)
            self.assertEqual(code, 0)
            code = run(root / "fuentes", root / "data", root / "control", strict=True, quiet=True)
            self.assertEqual(code, 1)

    def test_fail_on_delta_blocks_output(self) -> None:
        from metas_etl.cli import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_source(
                root / "fuentes" / "METAS FORMACION AGOSTO 26 - 2026.csv",
                [
                    ["Meta", "100"],
                    ["Ejecución", "80"],
                    ["INDICADOR", "Meta 2026", "Ejecución", "% Ejecución", "Estado"],
                    ["Tecnólogos - Presencial", "110", "80", "72%", "Buena"],
                    ["TOTAL FORMACION COMPLEMENTARIA", "100", "80", "", ""],
                ],
            )
            code = run(
                root / "fuentes",
                root / "data",
                root / "control",
                fail_on_delta=True,
                quiet=True,
            )
            self.assertEqual(code, 1)
            self.assertEqual(list((root / "data").glob("*.xlsx")), [])


if __name__ == "__main__":
    unittest.main()
