from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from metas_etl.catalog import INDICATORS
from metas_etl.normalize import FIELDS, assert_contract, normalize_file, parse_int
from metas_etl.persist import write_fact


class UnitTests(unittest.TestCase):
    def test_spanish_integer_formats(self) -> None:
        self.assertEqual(parse_int("1.523"), 1523)
        with self.assertRaises(ValueError):
            parse_int("1,5")
        self.assertEqual(parse_int("-"), 0)
        self.assertEqual(parse_int(None), 0)

    def test_catalog_has_unique_atomic_keys(self) -> None:
        keys = [(i.id_categoria, i.id_nivel) for i in INDICATORS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(INDICATORS), 28)

    def test_contract_rejects_duplicate_key(self) -> None:
        row = dict(zip(FIELDS, (1, 202605, 4, 4, 10, 3)))
        with self.assertRaises(AssertionError):
            assert_contract([row, row.copy()])


class IntegrationAndIdempotenceTests(unittest.TestCase):
    def test_normalizes_only_main_fpi_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)
            source = root / "METAS CENTRO ASTIN - CORTE 31 MAYO 2026.csv"
            rows = [
                ["Metas Formación Profesional Integral", "Meta", "Ejecución"],
                ["Tecnólogos Regular - Presencial", "1.523", "1.100"],
                ["Formación Complementaria CampeSENA", "45", "32"],
                ["TOTAL FORMACION COMPLEMENTARIA", "1.568", "1.132"],
                ["Retención"],
                ["Tecnólogos Regular - Presencial", "90%", "80%"],
            ]
            with source.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream, delimiter=";").writerows(rows)
            facts, info = normalize_file(source)
            self.assertEqual(info["periodo"], 202605)
            self.assertEqual(len(facts), 2)
            self.assertEqual(sum(r["Meta"] for r in facts), 1568)
            out = root / "fact.csv"
            write_fact(out, facts)
            first = out.read_bytes()
            write_fact(out, facts)
            self.assertEqual(out.read_bytes(), first)
            with out.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(tuple(next(csv.reader(stream, delimiter=";"))), FIELDS)

    def test_generated_nonnegative_values_preserve_integer_contract(self) -> None:
        # Propiedad determinista sobre una muestra reproducible de formatos locales.
        for n in range(0, 1000, 7):
            formatted = f"{n:,}".replace(",", ".")
            self.assertEqual(parse_int(formatted), n)
            self.assertGreaterEqual(parse_int(formatted), 0)


if __name__ == "__main__":
    unittest.main()
