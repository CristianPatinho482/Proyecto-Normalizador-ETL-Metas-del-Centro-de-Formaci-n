"""Interfaz de línea de comandos y orquestación del lote multitemporal.

El lote es determinista:
- descubre fuentes en orden estable;
- normaliza cada fuente en memoria;
- resuelve duplicados del mismo periodo con una política explícita;
- escribe solo después de verificar el contrato del libro;
- registra un manifiesto sin marcas de tiempo para que dos ejecuciones
  idénticas produzcan los mismos bytes.

Política de periodos:
- ``error`` (predeterminada): dos fuentes del mismo periodo con hechos
  distintos son un conflicto y no se escribe ninguna salida para ese periodo.
- ``latest``: se elige la fuente con la fecha de corte más reciente y las
  demás se registran como duplicados.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .catalog import SCHEMA_VERSION
from .config import DEFAULT_CONTROL, DEFAULT_OUTPUT, DEFAULT_SOURCE, ID_CENTRO_ASTIN
from .errors import ContractViolation, SourceNotRecognized
from .io import discover
from .normalize import normalize_file
from .persist import atomic_bytes, csv_bytes, write_json
from .workbook import build_workbook, facts_hash

OUTPUT_FORMATS = ("xlsx", "csv", "both")
PERIOD_POLICIES = ("error", "latest")


@dataclass
class _Candidate:
    path: Path
    facts: list[dict[str, int]]
    info: dict[str, object]


def _emit(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:  # consolas Windows con cp1252
        print(text.encode("ascii", "replace").decode("ascii"))


def _sort_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    suffix_priority = {".xlsx": 3, ".xlsm": 2, ".csv": 1}

    def key(item: _Candidate) -> tuple[str, int, str, str]:
        return (
            str(item.info.get("fecha_corte", "")),
            suffix_priority.get(item.path.suffix.casefold(), 0),
            item.path.name.casefold(),
            str(item.path).casefold(),
        )

    return sorted(candidates, key=key, reverse=True)


def run(
    sources: Path | str | list[Path | str],
    output: Path,
    control: Path,
    id_centro: int = ID_CENTRO_ASTIN,
    *,
    sheet: str | None = None,
    period: int | None = None,
    output_format: str = "xlsx",
    period_policy: str = "error",
    strict: bool = False,
    fail_on_delta: bool = False,
    quiet: bool = False,
) -> int:
    """Ejecuta el lote y retorna 1 si hubo errores, 0 si terminó correctamente."""

    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"Formato de salida no admitido: {output_format!r}")
    if period_policy not in PERIOD_POLICIES:
        raise ValueError(f"Política de periodos no admitida: {period_policy!r}")

    output = Path(output)
    control = Path(control)
    files = discover(sources)
    if not files:
        raise ValueError(f"No se encontraron fuentes CSV/XLSX/XLSM en {sources!r}")
    if (sheet is not None or period is not None) and len(files) != 1:
        raise ValueError("--sheet y --period solo se pueden usar con una única fuente")

    manifest: dict[str, object] = {
        "version": 2,
        "schema": SCHEMA_VERSION,
        "etl_version": __version__,
        "id_centro": id_centro,
        "output_format": output_format,
        "period_policy": period_policy,
        "procesados": [],
        "omitidos": [],
        "duplicados": [],
        "errores": [],
    }
    processed = manifest["procesados"]
    omitted = manifest["omitidos"]
    duplicates = manifest["duplicados"]
    errors = manifest["errores"]
    assert isinstance(processed, list)
    assert isinstance(omitted, list)
    assert isinstance(duplicates, list)
    assert isinstance(errors, list)

    candidates: list[_Candidate] = []
    for file in files:
        try:
            facts, info = normalize_file(
                file,
                id_centro,
                sheet=sheet,
                period=period,
            )
            candidates.append(_Candidate(file, facts, info))
        except SourceNotRecognized as exc:
            omitted.append({"fuente": file.name, "motivo": str(exc)})
            if not quiet:
                _emit(f"OMITIDO  {file.name}: {exc}")
        except (ContractViolation, ValueError, TypeError, OSError, RuntimeError, AssertionError) as exc:
            errors.append({"fuente": file.name, "error": str(exc)})
            if not quiet:
                _emit(f"ERROR    {file.name}: {exc}")

    by_period: dict[int, list[_Candidate]] = {}
    for candidate in candidates:
        by_period.setdefault(int(candidate.info["periodo"]), []).append(candidate)

    for period_value in sorted(by_period):
        group = _sort_candidates(by_period[period_value])
        chosen = group[0]
        rejected = group[1:]

        if rejected:
            all_equal = all(item.facts == chosen.facts for item in rejected)
            if not all_equal and period_policy == "error":
                errors.append(
                    {
                        "periodo": period_value,
                        "error": "Conflicto de periodo: fuentes con hechos distintos",
                        "fuentes": [item.path.name for item in group],
                    }
                )
                if not quiet:
                    _emit(
                        f"ERROR    {period_value}: fuentes con hechos distintos "
                        f"({', '.join(item.path.name for item in group)})"
                    )
                continue
            reason = (
                "Mismo periodo y mismos hechos"
                if all_equal
                else "Corte anterior del mismo periodo (política latest)"
            )
            for item in rejected:
                duplicates.append(
                    {
                        "fuente": item.path.name,
                        "periodo": period_value,
                        "sha256_fuente": item.info.get("sha256_fuente", ""),
                        "fecha_corte": item.info.get("fecha_corte", ""),
                        "motivo": reason,
                    }
                )
                if not quiet:
                    _emit(f"DUPLICADO {item.path.name}: {reason}")

        info = chosen.info
        delta = info.get("diferencia_hojas_vs_total")
        if fail_on_delta and isinstance(delta, dict) and (
            delta["meta"] != 0 or delta["ejecucion"] != 0
        ):
            errors.append(
                {
                    "fuente": chosen.path.name,
                    "periodo": period_value,
                    "error": (
                        "Diferencia entre hojas atómicas y total reportado: "
                        f"Meta={delta['meta']}, Ejecución={delta['ejecucion']}"
                    ),
                }
            )
            if not quiet:
                _emit(
                    f"ERROR    {chosen.path.name}: diferencia de conciliación "
                    f"Meta={delta['meta']} Ejecución={delta['ejecucion']}"
                )
            continue

        base_name = (
            f"Modelo_Normalizado_Metas_Centro_ASTIN_"
            f"{period_value // 100}_{period_value % 100:02d}"
        )
        outputs: list[dict[str, object]] = []
        try:
            if output_format in {"xlsx", "both"}:
                data = build_workbook(chosen.facts, info, id_centro=id_centro)
                target = output / f"{base_name}.xlsx"
                atomic_bytes(target, data)
                outputs.append(
                    {
                        "formato": "xlsx",
                        "archivo": target.name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            if output_format in {"csv", "both"}:
                data = csv_bytes(chosen.facts)
                target = output / f"{base_name}.csv"
                atomic_bytes(target, data)
                outputs.append(
                    {
                        "formato": "csv",
                        "archivo": target.name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
        except (ContractViolation, ValueError, TypeError, OSError, RuntimeError, AssertionError) as exc:
            errors.append({"fuente": chosen.path.name, "periodo": period_value, "error": str(exc)})
            if not quiet:
                _emit(f"ERROR    {chosen.path.name}: {exc}")
            continue

        info["salidas"] = outputs
        info["hash_hecho"] = facts_hash(chosen.facts)
        processed.append(info)
        if not quiet:
            names = ", ".join(str(item["archivo"]) for item in outputs)
            _emit(
                f"OK       {info['periodo_legible']}  {info['filas_hecho']} filas  "
                f"Meta={info['suma_hojas']['meta']}  "
                f"Ejecución={info['suma_hojas']['ejecucion']}  {names}"
            )

    processed.sort(key=lambda item: int(item["periodo"]))
    omitted.sort(key=lambda item: str(item["fuente"]).casefold())
    duplicates.sort(key=lambda item: (int(item["periodo"]), str(item["fuente"]).casefold()))
    errors.sort(
        key=lambda item: (
            int(item.get("periodo", 0)),
            str(item.get("fuente", "")).casefold(),
            str(item.get("error", "")),
        )
    )

    periods = [int(item["periodo"]) for item in processed]
    manifest["resumen"] = {
        "archivos_descubiertos": len(files),
        "procesados": len(processed),
        "omitidos": len(omitted),
        "duplicados": len(duplicates),
        "errores": len(errors),
        "periodos": periods,
        "periodo_min": min(periods) if periods else None,
        "periodo_max": max(periods) if periods else None,
    }

    write_json(control / "manifiesto_metas.json", manifest)

    if not quiet:
        _emit(
            f"Lote: {len(processed)} periodos, {len(omitted)} omitidos, "
            f"{len(duplicates)} duplicados, {len(errors)} errores. "
            f"Manifiesto: {control / 'manifiesto_metas.json'}"
        )

    return 1 if errors or (strict and omitted) else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalizador ETL multitemporal de Metas de Formación - Centro ASTIN"
    )
    parser.add_argument(
        "sources",
        type=Path,
        nargs="*",
        help=f"Archivos o carpetas de fuentes (predeterminado: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Carpeta de libros normalizados (predeterminado: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--control-output",
        type=Path,
        default=DEFAULT_CONTROL,
        help=f"Carpeta de manifiesto y auditoría (predeterminado: {DEFAULT_CONTROL})",
    )
    parser.add_argument("--id-centro", type=int, default=ID_CENTRO_ASTIN)
    parser.add_argument("--sheet", help="Hoja explícita; solo con una fuente")
    parser.add_argument("--period", type=int, help="Periodo YYYYMM explícito; solo con una fuente")
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=OUTPUT_FORMATS,
        default="xlsx",
        help="Formato de salida: xlsx (predeterminado), csv o both",
    )
    parser.add_argument(
        "--period-policy",
        choices=PERIOD_POLICIES,
        default="error",
        help="Resolución de fuentes duplicadas del mismo periodo",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Falla si hay fuentes omitidas además de errores",
    )
    parser.add_argument(
        "--fail-on-delta",
        action="store_true",
        help="Falla y no escribe periodos cuya suma atómica no cuadre con el total reportado",
    )
    parser.add_argument("--quiet", action="store_true", help="No imprime el resumen por consola")
    args = parser.parse_args()

    sources = args.sources or [DEFAULT_SOURCE]
    try:
        code = run(
            sources,
            args.output,
            args.control_output,
            args.id_centro,
            sheet=args.sheet,
            period=args.period,
            output_format=args.output_format,
            period_policy=args.period_policy,
            strict=args.strict,
            fail_on_delta=args.fail_on_delta,
            quiet=args.quiet,
        )
    except (ValueError, OSError, ContractViolation) as exc:
        _emit(f"ERROR FATAL: {exc}")
        code = 2
    raise SystemExit(code)
