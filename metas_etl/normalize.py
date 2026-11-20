"""Normalización a la tabla de hechos atómica en 1FN.

Contratos de Hoare
------------------
Precondiciones (P):
    P1. La fuente existe, es legible y no es un bloqueo de Excel.
    P2. El periodo YYYYMM es inferible o fue suministrado explícitamente.
    P3. Existe al menos una fila atómica del catálogo antes del cierre de FPI.
    P4. Las cantidades son enteras y no negativas.
    P5. No hay dos filas atómicas con la misma clave
        ``(IdCentro, IdPeriodo, IdCategoria, IdNivelFormación)``.

Postcondiciones (Q):
    Q1. Cada hecho tiene exactamente los seis campos canónicos y todos son int.
    Q2. La clave compuesta es única.
    Q3. ``Meta >= 0`` y ``Ejecución >= 0``.
    Q4. No se emiten subtotales, porcentajes, retención ni certificación.
    Q5. La suma de Meta/Ejecución es la suma de las hojas atómicas, no la de
        los totales de cabecera. Si el total reportado difiere, la diferencia
        se registra y no se ajusta.
    Q6. Reejecutar sobre la misma fuente produce exactamente los mismos hechos
        y el mismo diccionario de control.

Invariantes de ciclo:
    I1. ``by_key`` contiene solo claves únicas ya procesadas.
    I2. Cada valor de ``by_key`` satisface el contrato de hecho.
    I3. La suma acumulada es la suma de las filas aceptadas hasta el momento.
"""

from __future__ import annotations

from pathlib import Path

from .catalog import (
    ALIAS_TO_INDICATOR,
    SCHEMA_VERSION,
    indicator_for,
    norm,
)
from .errors import ContractViolation, SourceNotRecognized
from .io import SourceDocument, infer_period, read_source, validate_period
from .rules import (
    extract_atomic,
    is_non_atomic_section,
    is_subtotal_label,
    is_total_complementaria,
    parse_int,
)

__all__ = [
    "FACT_FIELDS",
    "FIELDS",
    "assert_contract",
    "assert_normalization_postconditions",
    "infer_period",
    "is_subtotal_label",
    "normalize_file",
    "parse_int",
]

FIELDS = ("IdCentro", "IdPeriodo", "IdCategoria", "IdNivelFormación", "Meta", "Ejecución")
FACT_FIELDS = FIELDS


def _row_values(row: list[object]) -> tuple[str, object, object] | None:
    """Alias de compatibilidad para la extracción de una fila atómica."""

    return extract_atomic(row)


def _safe_parse_int(value: object) -> int | None:
    try:
        return parse_int(value)
    except ValueError:
        return None


def _reported_totals(rows: list[list[object]]) -> tuple[dict[str, int] | None, list[str]]:
    """Lee los totales de cabecera sin usarlos para construir hechos.

    La familia de agosto-octubre declara ``Meta`` y ``Ejecución`` en las
    primeras filas. La familia de abril-mayo declara el gran total dentro de
    la tabla FPI. Se ignoran las filas de porcentaje.
    """

    warnings: list[str] = []
    values: dict[str, int] = {}

    for row in rows[:20]:
        cells = [str(value).strip() if value is not None else "" for value in row]
        nonempty = [(index, value) for index, value in enumerate(cells) if value]
        if not nonempty:
            continue
        index, label = nonempty[0]
        if "%" in label:
            continue
        key = norm(label)
        if key not in {"meta", "ejecucion"}:
            continue
        raw_value = row[index + 1] if index + 1 < len(row) else None
        parsed = _safe_parse_int(raw_value)
        if parsed is None:
            warnings.append(f"No se pudo leer el total reportado de {label!r}: {raw_value!r}")
            continue
        values[key] = parsed

    if "meta" in values and "ejecucion" in values:
        return values, warnings

    for row in rows:
        cells = [str(value).strip() if value is not None else "" for value in row]
        for index, label in enumerate(cells):
            if not label:
                continue
            normalized = norm(label)
            if not normalized.startswith("total formacion profesional integral"):
                continue
            meta_raw = row[index + 1] if index + 1 < len(row) else None
            ejecucion_raw = row[index + 2] if index + 2 < len(row) else None
            meta = _safe_parse_int(meta_raw)
            ejecucion = _safe_parse_int(ejecucion_raw)
            if meta is None or ejecucion is None:
                warnings.append(
                    "No se pudo leer el total reportado de Formación Profesional Integral"
                )
                return None, warnings
            return {"meta": meta, "ejecucion": ejecucion}, warnings

    return None, warnings


def _classify_reconciliation(delta: dict[str, int] | None) -> str:
    if delta is None:
        return "SIN_TOTAL_REPORTADO"
    if delta["meta"] == 0 and delta["ejecucion"] == 0:
        return "CUADRA"
    return "DIFERENCIA_FUENTE"


def normalize_file(
    path: Path,
    id_centro: int = 1,
    *,
    sheet: str | None = None,
    period: int | None = None,
    source_document: SourceDocument | None = None,
) -> tuple[list[dict[str, int]], dict[str, object]]:
    """Normaliza un corte mensual y retorna ``(hechos, control)``.

    El resultado es determinista: los hechos se ordenan por
    ``(IdCategoria, IdNivelFormación)`` y el diccionario de control no contiene
    marcas de tiempo de ejecución.
    """

    if type(id_centro) is not int or id_centro <= 0:
        raise ContractViolation(f"IdCentro inválido: {id_centro!r}")

    document = source_document or read_source(path, sheet=sheet, period=period)
    validate_period(document.period)
    if period is not None and document.period != period:
        raise ContractViolation("El periodo del documento no coincide con el solicitado")

    facts_by_key: dict[tuple[int, int], dict[str, int]] = {}
    recognized = 0

    for line_no, row in enumerate(document.rows, start=1):
        if is_total_complementaria(row):
            break
        if facts_by_key and is_non_atomic_section(row):
            break
        parsed = extract_atomic(row)
        if parsed is None:
            continue
        label, meta_raw, ejecucion_raw = parsed
        indicator = ALIAS_TO_INDICATOR[norm(label)]
        meta = parse_int(meta_raw)
        ejecucion = parse_int(ejecucion_raw)
        if meta < 0 or ejecucion < 0:
            raise ContractViolation(
                f"Cantidad negativa en {document.path.name}:{line_no} ({label!r})"
            )
        key = (indicator.id_categoria, indicator.id_nivel)
        if key in facts_by_key:
            raise ContractViolation(
                f"Clave atómica duplicada {key} en periodo {document.period}, "
                f"{document.path.name}:{line_no}"
            )
        # Verificación defensiva: el par debe existir en la dimensión.
        indicator_for(*key)
        facts_by_key[key] = {
            "IdCentro": id_centro,
            "IdPeriodo": document.period,
            "IdCategoria": key[0],
            "IdNivelFormación": key[1],
            "Meta": meta,
            "Ejecución": ejecucion,
        }
        recognized += 1

    if not facts_by_key:
        raise SourceNotRecognized(
            f"No se identificaron hechos atómicos en {document.path.name!r}"
        )

    facts = sorted(
        facts_by_key.values(),
        key=lambda item: (item["IdCategoria"], item["IdNivelFormación"]),
    )
    assert_contract(facts, expected_center=id_centro, expected_period=document.period)

    reported, warnings = _reported_totals(document.rows)
    sums = {
        "meta": sum(item["Meta"] for item in facts),
        "ejecucion": sum(item["Ejecución"] for item in facts),
    }
    delta = (
        {
            "meta": sums["meta"] - reported["meta"],
            "ejecucion": sums["ejecucion"] - reported["ejecucion"],
        }
        if reported is not None
        else None
    )
    status = _classify_reconciliation(delta)
    if status == "DIFERENCIA_FUENTE":
        warnings.append(
            "El total de cabecera no coincide con la suma de hojas atómicas; "
            "la diferencia es de la fuente y no se ajusta automáticamente"
        )

    info: dict[str, object] = {
        "version_esquema": SCHEMA_VERSION,
        "id_centro": id_centro,
        "fuente": document.path.name,
        "hoja": document.sheet,
        "periodo": document.period,
        "periodo_legible": f"{document.period // 100}-{document.period % 100:02d}",
        "fecha_corte": document.cut_date.isoformat(),
        "regla_periodo": document.period_evidence,
        "layout": document.layout,
        "sha256_fuente": document.sha256,
        "filas_hecho": len(facts),
        "indicadores_reconocidos": recognized,
        "suma_hojas": sums,
        "total_reportado": reported,
        "diferencia_hojas_vs_total": delta,
        "estado_conciliacion": status,
        "advertencias": warnings,
    }
    assert_normalization_postconditions(facts, info)
    return facts, info


def assert_contract(
    facts: list[dict[str, int]],
    *,
    expected_center: int | None = None,
    expected_period: int | None = None,
) -> None:
    """Verifica Q1-Q4 sobre una lista de hechos."""

    if not facts:
        raise ContractViolation("La tabla de hechos no puede estar vacía")
    keys: list[tuple[int, int, int, int]] = []
    for row in facts:
        if len(row) != len(FIELDS) or set(row) != set(FIELDS):
            raise ContractViolation(
                f"El hecho debe tener exactamente los campos {FIELDS}: {row!r}"
            )
        for field in FIELDS:
            value = row[field]
            if type(value) is not int:
                raise ContractViolation(f"El campo {field} debe ser int: {value!r}")
        if row["IdCentro"] <= 0:
            raise ContractViolation(f"IdCentro debe ser positivo: {row['IdCentro']}")
        validate_period(row["IdPeriodo"])
        if row["Meta"] < 0 or row["Ejecución"] < 0:
            raise ContractViolation(f"Cantidad negativa: {row!r}")
        if expected_center is not None and row["IdCentro"] != expected_center:
            raise ContractViolation("IdCentro inconsistente en la tabla de hechos")
        if expected_period is not None and row["IdPeriodo"] != expected_period:
            raise ContractViolation("IdPeriodo inconsistente en la tabla de hechos")
        keys.append(
            (
                row["IdCentro"],
                row["IdPeriodo"],
                row["IdCategoria"],
                row["IdNivelFormación"],
            )
        )
    if len(keys) != len(set(keys)):
        raise ContractViolation("La clave compuesta (IdCentro, IdPeriodo, IdCategoria, IdNivelFormación) debe ser única")


def assert_normalization_postconditions(
    facts: list[dict[str, int]],
    info: dict[str, object],
) -> None:
    """Verifica Q5-Q6 y la coherencia del diccionario de control."""

    assert_contract(
        facts,
        expected_center=int(info["id_centro"]) if "id_centro" in info else None,
        expected_period=int(info["periodo"]),
    )
    sums = {
        "meta": sum(row["Meta"] for row in facts),
        "ejecucion": sum(row["Ejecución"] for row in facts),
    }
    if sums != info["suma_hojas"]:
        raise ContractViolation("La suma de hechos no coincide con suma_hojas")
    if info["filas_hecho"] != len(facts):
        raise ContractViolation("filas_hecho no coincide con la tabla de hechos")
    if info["estado_conciliacion"] == "CUADRA":
        delta = info["diferencia_hojas_vs_total"]
        if not isinstance(delta, dict) or delta["meta"] != 0 or delta["ejecucion"] != 0:
            raise ContractViolation("Estado CUADRA incompatible con una diferencia distinta de cero")
