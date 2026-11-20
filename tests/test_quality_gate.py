"""Pruebas de calidad, conservación y multiesquema del ETL de Metas."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from metas_etl.catalog import ALIAS_TO_INDICATOR, INDICATORS, norm
from metas_etl.cli import run
from metas_etl.io import read_rows
from metas_etl.normalize import (
    FIELDS,
    _row_values,
    assert_contract,
    infer_period,
    is_subtotal_label,
    normalize_file,
    parse_int,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCES = ROOT / "Metas"

EXPECTED_REAL_COUNTS = {202604: 28, 202605: 28, 202608: 20, 202609: 20, 202610: 20}
EXPECTED_REAL_DELTAS = {
    202604: {"meta": 0, "ejecucion": 0},
    202605: {"meta": 0, "ejecucion": 0},
    202608: {"meta": 90, "ejecucion": 98},
    202609: {"meta": 90, "ejecucion": 98},
    202610: {"meta": 90, "ejecucion": 57},
}


def write_source(path: Path, rows: list[list[object]]) -> Path:
    """Escribe un corte sintético con el delimitador institucional."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter=";").writerows(rows)
    return path


def new_family_rows(
    selected: list[tuple[object, int, int]],
    *,
    extra_rows: list[list[object]] | None = None,
) -> list[list[object]]:
    """Construye un corte de la familia de 5 columnas (agosto-octubre)."""

    total_meta = sum(meta for _, meta, _ in selected)
    total_ejec = sum(ejec for _, _, ejec in selected)
    rows: list[list[object]] = [
        ["Centro Nacional de Asistencia Tecnica a la Industria - Astin", "", "", "", ""],
        ["Meta", str(total_meta), "", "", ""],
        ["Ejecución", str(total_ejec), "", "", ""],
        ["INDICADOR", "Meta 2026", "Ejecución", "% Ejecución", "Estado"],
    ]
    for indicator, meta, ejec in selected:
        rows.append([indicator.label, str(meta), str(ejec), "0,00%", "Baja"])
    rows.extend(extra_rows or [])
    rows.append(["TOTAL FORMACION COMPLEMENTARIA", str(total_meta), str(total_ejec), "", ""])
    return rows


def raw_atomic_sums(path: Path) -> tuple[int, int]:
    """Reconstruye la suma atómica desde el CSV, sin usar la tabla normalizada."""

    rows = read_rows(path)
    meta = 0
    ejecucion = 0
    seen: set[tuple[int, int]] = set()
    for row in rows:
        cells = [str(value).strip() if value is not None else "" for value in row]
        nonempty = [(index, value) for index, value in enumerate(cells) if value]
        if not nonempty:
            continue
        first_label = norm(nonempty[0][1])
        if first_label.startswith("total formacion complementaria") and "estrategia" not in first_label:
            break
        for index, label in nonempty:
            if is_subtotal_label(label):
                continue
            indicator = ALIAS_TO_INDICATOR.get(norm(label))
            if indicator is None:
                continue
            trailing = [value for position, value in nonempty if position > index]
            if len(trailing) < 2:
                continue
            key = (indicator.id_categoria, indicator.id_nivel)
            if key in seen:
                raise AssertionError(f"Clave atómica duplicada en {path.name}: {key}")
            seen.add(key)
            meta += parse_int(trailing[0])
            ejecucion += parse_int(trailing[1])
            break
    return meta, ejecucion


class UnitTests(unittest.TestCase):
    def test_parse_int_sanitizes_numbers_and_nulls(self) -> None:
        cases = {
            None: 0,
            "": 0,
            "-": 0,
            "—": 0,
            "–": 0,
            "NaN": 0,
            " 42 ": 42,
            "0": 0,
            "1.523": 1523,
            "1.523.456": 1523456,
            7: 7,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_int(raw), expected)
                self.assertGreaterEqual(parse_int(raw), 0)
        self.assertEqual(parse_int(7.0), 7)

    def test_parse_int_rejects_fractional_quantities(self) -> None:
        for raw in ("1,5", "1.5", "1.523,5", "-2,25"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_int(raw)

    def test_catalog_maps_labels_to_expected_dimension_keys(self) -> None:
        cases = {
            "TECNÓLOGOS CAMPESENA": (10, 4),
            "Tecnólogos - Presencial": (4, 4),
            "Técnico - Articulación Media": (16, 3),
            "Formación Complementaria CampeSENA": (10, 19),
            "Formación Complementaria Full Popular": (1, 20),
            "Placa huella 6": (3, 17),
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                indicator = ALIAS_TO_INDICATOR[norm(label)]
                self.assertEqual((indicator.id_categoria, indicator.id_nivel), expected)

    def test_infer_period_from_filename_and_header(self) -> None:
        cases = [
            ("METAS FORMACION AGOSTO 26 - 2026.csv", [], 202608),
            ("METAS FORMACION SEPTIEMBRE 28 - 2026.csv", [], 202609),
            ("METAS FORMACION OCTUBRE 15 - 2026.csv", [], 202610),
            ("EJECUCION METAS FORMACION CENTRO ASTIN - CORTE ABRIL 30.csv", [["Actualización: 30 de abril de 2026"]], 202604),
            ("METAS CENTRO ASTIN - CORTE 31 MAYO 2026.csv", [], 202605),
            ("corte.csv", [["Corte", "2026-07-31"]], 202607),
            ("corte.csv", [["Fecha", date(2026, 11, 30)]], 202611),
        ]
        for name, rows, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(infer_period(Path(name), rows), expected)

    def test_infer_period_without_evidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            infer_period(Path("corte.csv"), [["sin fecha"]])

    def test_subtotal_labels_are_not_atomic(self) -> None:
        labels = [
            "Total Tecnólogos",
            "TOTAL FORMACION COMPLEMENTARIA",
            "FORMACION TITULADA (H) = (B+G)",
            "Formación Especial Campesina (FEC) (O) = (M+N)",
            "FORMACIÓN TECNOLÓGICA (A)",
            "FORMACION TITULADA (A)",
            "Tecnólogos - Presencial TOTAL",
            "= Tecnólogos - Presencial",
            "Formación Complementaria Estrategia Full Popular",
        ]
        for label in labels:
            with self.subTest(label=label):
                self.assertIsNone(
                    _row_values([label, "1.523", "1.679", "110,24%", "Sobre ejecución"])
                )
        marker_labels = [
            "Total Tecnólogos",
            "TOTAL FORMACION COMPLEMENTARIA",
            "FORMACION TITULADA (H) = (B+G)",
            "Formación Especial Campesina (FEC) (O) = (M+N)",
            "FORMACION TITULADA (A)",
            "Tecnólogos - Presencial TOTAL",
            "= Tecnólogos - Presencial",
        ]
        for label in marker_labels:
            with self.subTest(marker=label):
                self.assertTrue(is_subtotal_label(label))

        self.assertIsNotNone(
            _row_values(
                ["Tecnólogos - Presencial", "1.523", "1.679", "110,24%", "Sobre ejecución"]
            )
        )

    def test_negative_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = write_source(
                Path(tmp) / "METAS FORMACION AGOSTO 26 - 2026.csv",
                new_family_rows(
                    [(INDICATORS[0], -1, 0)],
                    extra_rows=[],
                ),
            )
            with self.assertRaises(ValueError):
                normalize_file(source)


class IntegrationTests(unittest.TestCase):
    def test_conservation_and_subtotal_purge_are_exact(self) -> None:
        selected = [
            (INDICATORS[0], 1523, 1679),
            (INDICATORS[4], 52, 0),
            (INDICATORS[19], 3840, 2720),
            (INDICATORS[26], 645, 654),
        ]
        extra_rows = [
            ["Total Tecnólogos", "9.999", "9.999", "", ""],
            ["FORMACION TITULADA (H) = (B+G)", "9.999", "9.999", "", ""],
            ["FORMACIÓN TECNOLÓGICA (A)", "9.999", "9.999", "", ""],
            ["FORMACION TITULADA (A)", "9.999", "9.999", "", ""],
            ["Tecnólogos - Presencial TOTAL", "9.999", "9.999", "", ""],
            ["= Tecnólogos - Presencial", "9.999", "9.999", "", ""],
            ["Formación Complementaria Estrategia Full Popular", "9.999", "9.999", "", ""],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            source = write_source(
                Path(tmp) / "METAS FORMACION AGOSTO 26 - 2026.csv",
                new_family_rows(selected, extra_rows=extra_rows),
            )
            facts, info = normalize_file(source)
            again, info_again = normalize_file(source)

        self.assertEqual(facts, again)
        self.assertEqual(info, info_again)
        self.assertEqual(info["periodo"], 202608)
        self.assertEqual(len(facts), len(selected))
        self.assertEqual(
            info["suma_hojas"],
            {"meta": sum(meta for _, meta, _ in selected), "ejecucion": sum(ejec for _, _, ejec in selected)},
        )
        self.assertEqual(info["diferencia_hojas_vs_total"], {"meta": 0, "ejecucion": 0})
        assert_contract(facts)

        expected = {
            (indicator.id_categoria, indicator.id_nivel): (meta, ejec)
            for indicator, meta, ejec in selected
        }
        actual = {
            (row["IdCategoria"], row["IdNivelFormación"]): (row["Meta"], row["Ejecución"])
            for row in facts
        }
        self.assertEqual(actual, expected)
        for row in facts:
            self.assertEqual(set(row), set(FIELDS))
            for field in FIELDS:
                self.assertIsInstance(row[field], int)
                self.assertIsNotNone(row[field])
            self.assertGreater(row["IdCentro"], 0)
            self.assertGreater(row["IdPeriodo"], 0)
            self.assertGreaterEqual(row["Meta"], 0)
            self.assertGreaterEqual(row["Ejecución"], 0)

    def test_multischema_batch_keeps_one_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = root / "fuentes"
            write_source(
                sources / "EJECUCION METAS FORMACION CENTRO ASTIN - CORTE ABRIL 30 2026.csv",
                [
                    ["Metas Formación Profesional Integral", "Meta", "Ejecución", "% Ejecución"],
                    ["Tecnólogos - Presencial", "1.523", "1.530", "100,46%"],
                    ["Formación Complementaria CampeSENA", "45", "32", "71,11%"],
                    ["TOTAL FORMACION PROFESIONAL INTEGRAL", "1.568", "1.562", "99,62%"],
                ],
            )
            write_source(
                sources / "METAS FORMACION AGOSTO 26 - 2026.csv",
                new_family_rows(
                    [
                        (INDICATORS[0], 1523, 1530),
                        (INDICATORS[24], 45, 32),
                    ],
                ),
            )
            data = root / "data"
            control = root / "control"
            self.assertEqual(run(sources, data, control, output_format="both"), 0)

            xlsx_outputs = sorted(data.glob("*.xlsx"))
            csv_outputs = sorted(data.glob("*.csv"))
            self.assertEqual(
                [path.name for path in xlsx_outputs],
                [
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_04.xlsx",
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_08.xlsx",
                ],
            )
            self.assertEqual(
                [path.name for path in csv_outputs],
                [
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_04.csv",
                    "Modelo_Normalizado_Metas_Centro_ASTIN_2026_08.csv",
                ],
            )
            for path in csv_outputs:
                with path.open(encoding="utf-8", newline="") as stream:
                    reader = csv.DictReader(stream, delimiter=";")
                    self.assertEqual(reader.fieldnames, list(FIELDS))
                    rows = list(reader)
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertEqual(set(row), set(FIELDS))
                    for field in FIELDS:
                        self.assertNotIn(row[field], (None, ""))
                        int(row[field])
                    self.assertGreaterEqual(int(row["Meta"]), 0)
                    self.assertGreaterEqual(int(row["Ejecución"]), 0)
                keys = [
                    (row["IdCentro"], row["IdPeriodo"], row["IdCategoria"], row["IdNivelFormación"])
                    for row in rows
                ]
                self.assertEqual(len(keys), len(set(keys)))

            from openpyxl import load_workbook

            for path in xlsx_outputs:
                workbook = load_workbook(path, read_only=True, data_only=True)
                try:
                    fact_rows = list(workbook["FactMetas"].iter_rows(values_only=True))
                finally:
                    workbook.close()
                self.assertEqual(tuple(fact_rows[0]), FIELDS)
                self.assertEqual(len(fact_rows) - 1, 2)

            manifest = json.loads((control / "manifiesto_metas.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["errores"], [])
            self.assertEqual(len(manifest["procesados"]), 2)
            for item in manifest["procesados"]:
                self.assertEqual({entry["formato"] for entry in item["salidas"]}, {"xlsx", "csv"})

    def test_synthetic_rerun_is_byte_identical(self) -> None:
        selected = [
            (INDICATORS[0], 1523, 1679),
            (INDICATORS[4], 52, 0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_source(
                root / "METAS FORMACION AGOSTO 26 - 2026.csv",
                new_family_rows(selected),
            )
            first = root / "first"
            second = root / "second"
            self.assertEqual(run(source, first / "data", first / "control"), 0)
            self.assertEqual(run(source, second / "data", second / "control"), 0)

            first_data = {path.name: path.read_bytes() for path in (first / "data").glob("*.xlsx")}
            second_data = {path.name: path.read_bytes() for path in (second / "data").glob("*.xlsx")}
            self.assertEqual(first_data, second_data)
            self.assertEqual(
                (first / "control" / "manifiesto_metas.json").read_bytes(),
                (second / "control" / "manifiesto_metas.json").read_bytes(),
            )


class HypothesisPropertyTests(unittest.TestCase):
    @settings(max_examples=50, deadline=None)
    @given(value=st.integers(min_value=0, max_value=10**9))
    def test_parse_int_spanish_thousands_roundtrip(self, value: int) -> None:
        formatted = f"{value:,}".replace(",", ".")
        self.assertEqual(parse_int(formatted), value)
        self.assertGreaterEqual(parse_int(formatted), 0)

    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        selected=st.lists(
            st.tuples(
                st.sampled_from(INDICATORS),
                st.integers(min_value=0, max_value=10**6),
                st.integers(min_value=0, max_value=10**6),
            ),
            min_size=1,
            max_size=len(INDICATORS),
            unique_by=lambda item: (item[0].id_categoria, item[0].id_nivel),
        )
    )
    def test_conservation_nonnegativity_and_idempotence(self, selected) -> None:
        total_meta = sum(meta for _, meta, _ in selected)
        total_ejecucion = sum(ejecucion for _, _, ejecucion in selected)
        rows = new_family_rows(
            selected,
            extra_rows=[
                ["Total Tecnólogos", "9.999", "9.999", "", ""],
                ["FORMACION TITULADA (H) = (B+G)", "9.999", "9.999", "", ""],
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = write_source(
                Path(tmp) / "METAS FORMACION AGOSTO 26 - 2026.csv",
                rows,
            )
            facts, info = normalize_file(source)
            again, info_again = normalize_file(source)

        self.assertEqual(facts, again)
        self.assertEqual(info, info_again)
        self.assertEqual(len(facts), len(selected))
        self.assertEqual(sum(row["Meta"] for row in facts), total_meta)
        self.assertEqual(sum(row["Ejecución"] for row in facts), total_ejecucion)
        self.assertEqual(info["diferencia_hojas_vs_total"], {"meta": 0, "ejecucion": 0})
        self.assertTrue(all(row["Meta"] >= 0 and row["Ejecución"] >= 0 for row in facts))
        assert_contract(facts)


@unittest.skipUnless(
    REAL_SOURCES.is_dir(),
    "No se encontró la carpeta Metas/ con los cortes reales del centro.",
)
class RealSourceTests(unittest.TestCase):
    def test_real_batch_contract_and_known_deltas(self) -> None:
        files = sorted(REAL_SOURCES.glob("*.csv"))
        self.assertEqual(len(files), 5)
        periods: set[int] = set()
        for path in files:
            facts, info = normalize_file(path)
            period = int(info["periodo"])
            periods.add(period)
            with self.subTest(period=period, source=path.name):
                self.assertEqual(info["filas_hecho"], EXPECTED_REAL_COUNTS[period])
                self.assertEqual(info["indicadores_reconocidos"], EXPECTED_REAL_COUNTS[period])
                self.assertEqual(info["diferencia_hojas_vs_total"], EXPECTED_REAL_DELTAS[period])
                assert_contract(facts)
                keys = [
                    (row["IdCentro"], row["IdPeriodo"], row["IdCategoria"], row["IdNivelFormación"])
                    for row in facts
                ]
                self.assertEqual(len(keys), len(set(keys)))
                for row in facts:
                    self.assertEqual(set(row), set(FIELDS))
                    for field in FIELDS:
                        self.assertIsInstance(row[field], int)
                        self.assertIsNotNone(row[field])
                    self.assertGreater(row["IdCentro"], 0)
                    self.assertGreater(row["IdPeriodo"], 0)
                    self.assertGreaterEqual(row["Meta"], 0)
                    self.assertGreaterEqual(row["Ejecución"], 0)
        self.assertEqual(periods, set(EXPECTED_REAL_COUNTS))

    def test_real_batch_atomic_conservation_is_zero(self) -> None:
        for path in sorted(REAL_SOURCES.glob("*.csv")):
            facts, info = normalize_file(path)
            raw_meta, raw_ejecucion = raw_atomic_sums(path)
            with self.subTest(source=path.name):
                self.assertEqual(raw_meta, sum(row["Meta"] for row in facts))
                self.assertEqual(raw_ejecucion, sum(row["Ejecución"] for row in facts))
                self.assertEqual(raw_meta, info["suma_hojas"]["meta"])
                self.assertEqual(raw_ejecucion, info["suma_hojas"]["ejecucion"])

    def test_real_batch_rerun_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            self.assertEqual(run(REAL_SOURCES, first / "data", first / "control"), 0)
            self.assertEqual(run(REAL_SOURCES, second / "data", second / "control"), 0)

            first_data = {path.name: path.read_bytes() for path in (first / "data").glob("*.xlsx")}
            second_data = {path.name: path.read_bytes() for path in (second / "data").glob("*.xlsx")}
            self.assertEqual(first_data, second_data)
            self.assertEqual(
                (first / "control" / "manifiesto_metas.json").read_bytes(),
                (second / "control" / "manifiesto_metas.json").read_bytes(),
            )
            manifest = json.loads(
                (first / "control" / "manifiesto_metas.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["errores"], [])
            self.assertEqual(len(manifest["procesados"]), 5)


if __name__ == "__main__":
    unittest.main()
