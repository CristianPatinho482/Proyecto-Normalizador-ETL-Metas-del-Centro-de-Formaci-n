"""Construcción y verificación del libro Excel mensual.

El libro materializa el esquema en estrella solicitado:

    FactMetas(IdCentro, IdPeriodo, IdCategoria, IdNivelFormación, Meta, Ejecución)

junto con ``DimCentro``, ``DimPeriodo``, ``DimCategoria``, ``DimNivelFormación``,
``DimIndicador`` y ``Control``. No se escribe la columna ``Porcentaje``: es una
medida calculada en DAX y mezclarla con conteos violaría la separación de
unidades de la especificación formal.

La serialización XLSX se normaliza (fechas ZIP fijas y orden estable) para que
dos ejecuciones con los mismos hechos produzcan exactamente los mismos bytes.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from . import __version__
from .catalog import CATEGORIES, INDICATORS, LEVELS, SCHEMA_VERSION
from .config import CENTER, MONTH_NAMES
from .errors import ContractViolation
from .normalize import FIELDS, assert_contract
from .persist import atomic_bytes

SHEET_ORDER = (
    "FactMetas",
    "DimCentro",
    "DimPeriodo",
    "DimCategoria",
    "DimNivelFormación",
    "DimIndicador",
    "Control",
)

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
_SIDE = Side(style="thin", color="B7C9D6")
_BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
_TABLE_STYLE = "TableStyleMedium2"


def facts_hash(facts: list[dict[str, int]]) -> str:
    """Hash canónico de los hechos, independiente de rutas y timestamps."""

    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in facts
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _style_header(worksheet, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = worksheet.cell(row=1, column=column)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.border = _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    worksheet.row_dimensions[1].height = 30
    worksheet.freeze_panes = "A2"
    worksheet.print_title_rows = "1:1"
    worksheet.sheet_view.showGridLines = False


def _autosize(worksheet, headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    for index, header in enumerate(headers, start=1):
        values = [header]
        values.extend("" if row[index - 1] is None else str(row[index - 1]) for row in rows)
        width = min(70, max(10, max(len(value) for value in values) + 2))
        worksheet.column_dimensions[get_column_letter(index)].width = width


def _write_table(
    worksheet,
    headers: tuple[str, ...],
    rows: list[tuple[object, ...]],
    *,
    table_name: str,
    number_formats: dict[int, str] | None = None,
) -> None:
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=1, column=column, value=header)
    for row_index, row in enumerate(rows, start=2):
        for column, value in enumerate(row, start=1):
            cell = worksheet.cell(row=row_index, column=column, value=value)
            cell.border = _BORDER
            if number_formats and column in number_formats:
                cell.number_format = number_formats[column]

    _style_header(worksheet, len(headers))
    _autosize(worksheet, headers, rows)

    if rows:
        reference = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
        table = Table(displayName=table_name, ref=reference)
        table.tableStyleInfo = TableStyleInfo(
            name=_TABLE_STYLE,
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        worksheet.add_table(table)


def _control_rows(
    facts: list[dict[str, int]],
    info: dict[str, object],
    *,
    id_centro: int,
    period: int,
    cut: date,
) -> list[tuple[str, object]]:
    reported = info.get("total_reportado")
    delta = info.get("diferencia_hojas_vs_total")
    sums = info["suma_hojas"]
    assert isinstance(sums, dict)

    return [
        ("Esquema", SCHEMA_VERSION),
        ("VersionETL", __version__),
        ("IdCentro", id_centro),
        ("IdPeriodo", period),
        ("Periodo", f"{period // 100}-{period % 100:02d}"),
        ("Anio", period // 100),
        ("Mes", period % 100),
        ("NombreMes", MONTH_NAMES[period % 100]),
        ("FechaCorte", cut),
        ("Fuente", info.get("fuente", "")),
        ("Hoja", info.get("hoja", "")),
        ("ReglaPeriodo", info.get("regla_periodo", "")),
        ("Sha256Fuente", info.get("sha256_fuente", "")),
        ("Layout", info.get("layout", "")),
        ("FilasHecho", len(facts)),
        ("IndicadoresReconocidos", info.get("indicadores_reconocidos", 0)),
        ("SumaMeta", sums["meta"]),
        ("SumaEjecucion", sums["ejecucion"]),
        ("TotalReportadoMeta", reported["meta"] if isinstance(reported, dict) else None),
        (
            "TotalReportadoEjecucion",
            reported["ejecucion"] if isinstance(reported, dict) else None,
        ),
        ("DeltaMeta", delta["meta"] if isinstance(delta, dict) else None),
        ("DeltaEjecucion", delta["ejecucion"] if isinstance(delta, dict) else None),
        ("EstadoConciliacion", info.get("estado_conciliacion", "")),
        ("Advertencias", " | ".join(str(item) for item in info.get("advertencias", []))),
        ("HashHecho", facts_hash(facts)),
    ]


def build_workbook(
    facts: list[dict[str, int]],
    info: dict[str, object],
    *,
    id_centro: int = 1,
) -> bytes:
    """Construye, canoniza y verifica el libro mensual. Retorna sus bytes."""

    period = int(info["periodo"])
    assert_contract(facts, expected_center=id_centro, expected_period=period)
    year, month = divmod(period, 100)
    cut = date.fromisoformat(str(info["fecha_corte"]))

    workbook = Workbook()
    workbook.remove(workbook.active)

    fact_sheet = workbook.create_sheet("FactMetas")
    _write_table(
        fact_sheet,
        FIELDS,
        [tuple(row[field] for field in FIELDS) for row in facts],
        table_name="tblFactMetas",
        number_formats={1: "0", 2: "0", 3: "0", 4: "0", 5: "#,##0", 6: "#,##0"},
    )

    center_sheet = workbook.create_sheet("DimCentro")
    _write_table(
        center_sheet,
        ("IdCentro", "CodigoCentro", "NombreCentro", "Regional"),
        [(CENTER["IdCentro"], CENTER["CodigoCentro"], CENTER["NombreCentro"], CENTER["Regional"])],
        table_name="tblDimCentro",
        number_formats={1: "0", 2: "0"},
    )

    period_sheet = workbook.create_sheet("DimPeriodo")
    _write_table(
        period_sheet,
        ("IdPeriodo", "Anio", "Mes", "NombreMes", "FechaCorte"),
        [(period, year, month, MONTH_NAMES[month], cut)],
        table_name="tblDimPeriodo",
        number_formats={1: "0", 2: "0", 3: "0", 5: "yyyy-mm-dd"},
    )

    category_sheet = workbook.create_sheet("DimCategoria")
    _write_table(
        category_sheet,
        ("IdCategoria", "Categoria"),
        [(identifier, label) for identifier, label in CATEGORIES],
        table_name="tblDimCategoria",
        number_formats={1: "0"},
    )

    level_sheet = workbook.create_sheet("DimNivelFormación")
    _write_table(
        level_sheet,
        ("IdNivelFormación", "NivelFormación"),
        [(identifier, label) for identifier, label in LEVELS],
        table_name="tblDimNivelFormacion",
        number_formats={1: "0"},
    )

    indicator_sheet = workbook.create_sheet("DimIndicador")
    indicator_rows = sorted(
        ((indicator.id_categoria, indicator.id_nivel, indicator.label) for indicator in INDICATORS),
        key=lambda item: (item[0], item[1]),
    )
    _write_table(
        indicator_sheet,
        ("IdCategoria", "IdNivelFormación", "Indicador"),
        indicator_rows,
        table_name="tblDimIndicador",
        number_formats={1: "0", 2: "0"},
    )

    control_sheet = workbook.create_sheet("Control")
    control_rows = _control_rows(facts, info, id_centro=id_centro, period=period, cut=cut)
    _write_table(
        control_sheet,
        ("Clave", "Valor"),
        control_rows,
        table_name="tblControl",
    )
    for row_index, (_, value) in enumerate(control_rows, start=2):
        cell = control_sheet.cell(row=row_index, column=2)
        if isinstance(value, date):
            cell.number_format = "yyyy-mm-dd"
        elif isinstance(value, int):
            cell.number_format = "#,##0"
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    control_sheet.column_dimensions["A"].width = 30
    control_sheet.column_dimensions["B"].width = 100

    workbook.properties.creator = "ETL Metas ASTIN"
    workbook.properties.lastModifiedBy = "ETL Metas ASTIN"
    workbook.properties.title = f"Metas de Formación ASTIN {MONTH_NAMES[month]} {year}"
    workbook.properties.subject = "Tabla de hechos atómica 1FN para esquema en estrella"
    workbook.properties.description = (
        "Normalización multitemporal de Metas de Formación del Centro ASTIN. "
        "Sin subtotales, porcentajes, retención ni certificación."
    )
    workbook.properties.keywords = "SENA;ASTIN;metas;Power BI;capa Silver"
    workbook.properties.category = "Capa Silver"
    workbook.properties.created = datetime(year, month, 1)
    workbook.properties.modified = datetime(year, month, 1)
    workbook.properties.revision = "1"

    buffer = io.BytesIO()
    workbook.save(buffer)
    data = _canonical_zip(buffer.getvalue(), timestamp=datetime(year, month, 1))
    verify_workbook_bytes(data, facts, info, id_centro=id_centro)
    return data


def _canonical_zip(data: bytes, *, timestamp: datetime) -> bytes:
    """Reescribe el ZIP con fechas y atributos fijos.

    openpyxl actualiza ``dcterms:modified`` con la hora de guardado; se
    reemplaza por una fecha determinista derivada del periodo. Sin esto, dos
    ejecuciones idénticas producirían bytes distintos aunque los hechos sean
    iguales.
    """

    fixed = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                if item.filename == "docProps/core.xml":
                    text = payload.decode("utf-8")
                    text = re.sub(
                        r"(<dcterms:created[^>]*>)[^<]*(</dcterms:created>)",
                        rf"\g<1>{fixed}\g<2>",
                        text,
                    )
                    text = re.sub(
                        r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                        rf"\g<1>{fixed}\g<2>",
                        text,
                    )
                    payload = text.encode("utf-8")
                normalized = zipfile.ZipInfo(item.filename, date_time=(1980, 1, 1, 0, 0, 0))
                normalized.compress_type = zipfile.ZIP_DEFLATED
                normalized.create_system = 0
                normalized.external_attr = 0o600 << 16
                target.writestr(normalized, payload)
    finally:
        source.close()
    return output.getvalue()


def verify_workbook_bytes(
    data: bytes,
    facts: list[dict[str, int]],
    info: dict[str, object],
    *,
    id_centro: int = 1,
) -> None:
    """Postcondición de serialización: el libro contiene exactamente Q1-Q4."""

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if tuple(workbook.sheetnames) != SHEET_ORDER:
            raise ContractViolation(
                f"El libro debe contener las hojas {SHEET_ORDER}: {tuple(workbook.sheetnames)}"
            )

        fact_rows = list(workbook["FactMetas"].iter_rows(values_only=True))
        if not fact_rows or tuple(fact_rows[0]) != FIELDS:
            raise ContractViolation(f"Encabezado de FactMetas inválido: {fact_rows[:1]}")
        expected = [tuple(row[field] for field in FIELDS) for row in facts]
        actual = [tuple(row) for row in fact_rows[1:]]
        if actual != expected:
            raise ContractViolation("Las filas de FactMetas no coinciden con los hechos normalizados")
        if "Porcentaje" in fact_rows[0]:
            raise ContractViolation("FactMetas no debe contener porcentajes")

        center_rows = list(workbook["DimCentro"].iter_rows(values_only=True))
        if center_rows[0] != ("IdCentro", "CodigoCentro", "NombreCentro", "Regional"):
            raise ContractViolation("Encabezado de DimCentro inválido")
        if len(center_rows) != 2 or center_rows[1][0] != id_centro:
            raise ContractViolation("DimCentro debe contener exactamente el centro procesado")

        period_rows = list(workbook["DimPeriodo"].iter_rows(values_only=True))
        if period_rows[0] != ("IdPeriodo", "Anio", "Mes", "NombreMes", "FechaCorte"):
            raise ContractViolation("Encabezado de DimPeriodo inválido")
        if len(period_rows) != 2 or period_rows[1][0] != int(info["periodo"]):
            raise ContractViolation("DimPeriodo no coincide con el periodo del hecho")

        category_rows = list(workbook["DimCategoria"].iter_rows(values_only=True))
        if len(category_rows) != len(CATEGORIES) + 1:
            raise ContractViolation("DimCategoria no contiene el catálogo canónico")
        level_rows = list(workbook["DimNivelFormación"].iter_rows(values_only=True))
        if len(level_rows) != len(LEVELS) + 1:
            raise ContractViolation("DimNivelFormación no contiene el catálogo canónico")
        indicator_rows = list(workbook["DimIndicador"].iter_rows(values_only=True))
        if len(indicator_rows) != len(INDICATORS) + 1:
            raise ContractViolation("DimIndicador no contiene el catálogo canónico")

        control = {
            row[0]: row[1]
            for row in workbook["Control"].iter_rows(min_row=2, values_only=True)
            if row and row[0] is not None
        }
        if control.get("IdPeriodo") != int(info["periodo"]):
            raise ContractViolation("Control.IdPeriodo no coincide con el hecho")
        if control.get("FilasHecho") != len(facts):
            raise ContractViolation("Control.FilasHecho no coincide con el hecho")
        if control.get("HashHecho") != facts_hash(facts):
            raise ContractViolation("Control.HashHecho no coincide con los hechos")
    finally:
        workbook.close()


def write_workbook(
    path: Path,
    facts: list[dict[str, int]],
    info: dict[str, object],
    *,
    id_centro: int = 1,
) -> bytes:
    """Construye, verifica y escribe el libro de forma atómica."""

    data = build_workbook(facts, info, id_centro=id_centro)
    atomic_bytes(path, data)
    return data
