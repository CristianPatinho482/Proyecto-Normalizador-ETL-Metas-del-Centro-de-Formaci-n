"""Lectura tolerante y determinista de fuentes CSV y Excel.

El módulo no modifica las fuentes. Para libros con varias hojas elige la hoja
con el corte más reciente inferible; el argumento ``sheet`` permite forzar una
hoja concreta. La lectura de Excel es de solo lectura y sin enlaces externos.

Contratos
---------
``read_source``
    Pre:  ``path`` existe, tiene sufijo .csv/.xlsx/.xlsm y no es un bloqueo.
    Post: retorna ``SourceDocument`` con periodo YYYYMM válido, fecha de corte,
          filas seleccionadas, hoja y hash SHA-256 del archivo.
    Falla con ``SourceNotRecognized`` si el archivo no es un corte mensual
    apilado o si no permite inferir el periodo.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .catalog import norm
from .errors import SourceNotRecognized
from .rules import count_atomic_labels, looks_like_wide_matrix

ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
PERIOD_MIN = 202001
PERIOD_MAX = 203012


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    sheet: str
    rows: list[list[object]]
    period: int
    cut_date: date
    layout: str
    sha256: str
    period_evidence: str


@dataclass(frozen=True)
class _DateCandidate:
    year: int | None
    month: int
    day: int | None
    score: int
    position: int


def _plain(text: object) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.replace("\xa0", " ").casefold()


def _month_in(text: str) -> int | None:
    normalized = norm(text)
    for name, number in MONTHS.items():
        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return number
    return None


def _year_in(text: str) -> int | None:
    matches = re.findall(r"\b(20\d{2})\b", _plain(text))
    return int(matches[-1]) if matches else None


def validate_period(period: int) -> int:
    """Valida el dominio YYYYMM de la especificación formal."""

    if not isinstance(period, int) or not PERIOD_MIN <= period <= PERIOD_MAX:
        raise ValueError(f"Periodo fuera de rango [2020-01, 2030-12]: {period!r}")
    month = period % 100
    if not 1 <= month <= 12:
        raise ValueError(f"Mes inválido en periodo: {period!r}")
    return period


def _date_candidates(text: str) -> list[_DateCandidate]:
    """Extrae fechas en los formatos vistos en los reportes institucionales."""

    plain = _plain(text)
    patterns = (
        # 31 de mayo de 2026 / 30 de abril del 2026
        rf"(?P<day>\d{{1,2}})\s*(?:de\s+)?(?P<month>{_MONTH_PATTERN})\s*(?:de\s+|del\s+)?(?P<year>20\d{{2}})",
        # AGOSTO 26 - 2026 / Mayo2026
        rf"(?P<month>{_MONTH_PATTERN})\s*(?:de\s+)?(?P<day>\d{{1,2}})?\s*[\-–]?\s*(?P<year>20\d{{2}})",
        # 2026-05-31
        r"(?P<year>20\d{2})[-/](?P<month_num>\d{1,2})[-/](?P<day>\d{1,2})",
        # 31/05/2026
        r"(?P<day>\d{1,2})[-/](?P<month_num>\d{1,2})[-/](?P<year>20\d{2})",
        # 30 ABRIL (sin año; el año se infiere del encabezado)
        rf"(?P<day>\d{{1,2}})\s*(?:de\s+)?(?P<month>{_MONTH_PATTERN})\b",
        # ABRIL 20 (sin año)
        rf"(?P<month>{_MONTH_PATTERN})\s*(?:de\s+)?(?P<day>\d{{1,2}})\b",
    )

    candidates: list[_DateCandidate] = []
    for pattern_index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, plain):
            groups = match.groupdict()
            month_text = groups.get("month")
            month_num = groups.get("month_num")
            month = MONTHS.get(month_text or "", int(month_num) if month_num and month_num.isdigit() else 0)
            if not 1 <= month <= 12:
                continue
            day_text = groups.get("day")
            day = int(day_text) if day_text and day_text.isdigit() else None
            if day is not None and not 1 <= day <= 31:
                day = None
            year_text = groups.get("year")
            year = int(year_text) if year_text else None

            context = plain[max(0, match.start() - 60) : match.end() + 60]
            score = 1
            if year is not None:
                score += 10
            if any(token in context for token in ("actualiz", "ultima", "corte", "vigencia")):
                score += 8
            if "fecha" in context:
                score += 4
            # Un patrón más específico (fecha completa) vale un poco más.
            score += max(0, 4 - pattern_index)
            candidates.append(
                _DateCandidate(
                    year=year,
                    month=month,
                    day=day,
                    score=score,
                    position=match.start(),
                )
            )
    return candidates


def _best_dated_candidate(text: str) -> _DateCandidate | None:
    candidates = [candidate for candidate in _date_candidates(text) if candidate.year is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.score, candidate.position))


def _infer_period(
    path: Path,
    rows: list[list[object]],
    sheet_title: str,
    override: int | None = None,
) -> tuple[int, str]:
    if override is not None:
        return validate_period(override), "argumento --period"

    header_text = "\n".join(
        str(value)
        for row in rows[:25]
        for value in row
        if value is not None and str(value).strip()
    )

    # 1. Fecha completa en el nombre del archivo.
    candidate = _best_dated_candidate(path.stem)
    if candidate is not None:
        return validate_period(candidate.year * 100 + candidate.month), "fecha en nombre de archivo"

    # 2. Fecha completa en el título de la hoja ("30 ABRIL" no tiene año).
    candidate = _best_dated_candidate(sheet_title)
    if candidate is not None:
        return validate_period(candidate.year * 100 + candidate.month), "fecha en título de hoja"

    # 3. Fecha completa en el encabezado. Se prefiere la línea de actualización
    # o corte más reciente; así "corte mensual 31 de enero" no gana frente a
    # "actualización ... 20 de abril".
    candidate = _best_dated_candidate(header_text)
    if candidate is not None:
        return validate_period(candidate.year * 100 + candidate.month), "fecha en encabezado"

    # 4. Combinación de mes en nombre/hoja/encabezado y año en otra evidencia.
    for month_source, month_text in (
        ("nombre de archivo", path.stem),
        ("título de hoja", sheet_title),
        ("encabezado", header_text),
    ):
        month = _month_in(month_text)
        if month is None:
            continue
        for year_source, year_text in (
            ("nombre de archivo", path.stem),
            ("título de hoja", sheet_title),
            ("encabezado", header_text),
        ):
            year = _year_in(year_text)
            if year is not None:
                return (
                    validate_period(year * 100 + month),
                    f"mes en {month_source}, año en {year_source}",
                )

    raise SourceNotRecognized(
        f"No se pudo inferir el periodo YYYYMM de {path.name!r}; "
        "el nombre, la hoja y el encabezado no contienen una fecha utilizable"
    )


def infer_period(path: Path, rows: list[list[object]], sheet_title: str = "") -> int:
    """API compatible para pruebas: retorna solo el periodo inferido."""

    return _infer_period(path, rows, sheet_title)[0]


def infer_cut_date(
    path: Path,
    rows: list[list[object]],
    sheet_title: str,
    period: int,
) -> date:
    """Infiere la fecha de corte; si no hay día usa el último día del mes."""

    year, month = divmod(period, 100)
    last_day = calendar.monthrange(year, month)[1]

    evidence_texts = [sheet_title, path.stem]
    evidence_texts.extend(
        str(value)
        for row in rows[:25]
        for value in row
        if value is not None and str(value).strip()
    )

    days: list[int] = []
    for text in evidence_texts:
        for candidate in _date_candidates(text):
            if candidate.month != month:
                continue
            if candidate.year is not None and candidate.year != year:
                continue
            if candidate.day is not None and 1 <= candidate.day <= last_day:
                days.append(candidate.day)

    day = max(days) if days else last_day
    return date(year, month, min(day, last_day))


def _sniff_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines()[:25] if line.strip()]
    for delimiter in (";", "\t", "|", ","):
        counts = [line.count(delimiter) for line in lines]
        positive = [count for count in counts if count > 0]
        if positive and len(set(positive)) == 1:
            return delimiter
    return ";"


def _read_csv(path: Path) -> list[list[object]]:
    data = path.read_bytes()
    text = ""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    delimiter = _sniff_delimiter(text)
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _sheet_key(
    rows: list[list[object]],
    title: str,
    path: Path,
    override_period: int | None,
) -> tuple[int, int, int, int]:
    count = count_atomic_labels(rows)
    try:
        period = _infer_period(path, rows, title, override_period)[0]
    except SourceNotRecognized:
        period = 0
    cut = 0
    if period:
        cut = infer_cut_date(path, rows, title, period).toordinal()
    return (1 if count else 0, period, cut, count)


def _read_xlsx(path: Path, sheet: str | None) -> tuple[str, list[list[object]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependencia declarada
        raise RuntimeError(
            "Para leer XLSX instala las dependencias: pip install -r requirements.txt"
        ) from exc

    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        if sheet is not None:
            if sheet not in workbook.sheetnames:
                raise ValueError(f"La hoja {sheet!r} no existe en {path.name}")
            worksheet = workbook[sheet]
            return sheet, [list(row) for row in worksheet.iter_rows(values_only=True)]

        best: tuple[tuple[int, int, int, int], str, list[list[object]]] | None = None
        for worksheet in workbook.worksheets:
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            key = _sheet_key(rows, worksheet.title, path, None)
            if best is None or key > best[0]:
                best = (key, worksheet.title, rows)
        if best is None:
            raise ValueError(f"El libro {path.name} no contiene hojas")
        return best[1], best[2]
    finally:
        workbook.close()


def read_rows(path: Path, sheet: str | None = None) -> list[list[object]]:
    """Lee las filas crudas; no valida periodo ni etiquetas."""

    if path.suffix.casefold() == ".csv":
        return _read_csv(path)
    return _read_xlsx(path, sheet)[1]


def discover(sources: Path | str | Iterable[Path | str]) -> list[Path]:
    """Descubre fuentes no recursivas, sin bloqueos ni salidas del ETL."""

    if isinstance(sources, (str, Path)):
        roots = [Path(sources)]
    else:
        roots = [Path(source) for source in sources]

    files: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix.casefold() not in ALLOWED_SUFFIXES:
                raise ValueError(f"Sufijo no admitido: {root}")
            files.append(root)
        elif root.is_dir():
            for candidate in root.iterdir():
                if not candidate.is_file():
                    continue
                name = candidate.name.casefold()
                if name.startswith(("~$", ".")):
                    continue
                if candidate.suffix.casefold() not in ALLOWED_SUFFIXES:
                    continue
                if name.startswith(("modelo_normalizado_metas_centro_astin", "consolidado_metas")):
                    continue
                files.append(candidate)
        else:
            raise FileNotFoundError(f"No existe la fuente: {root}")

    seen: set[Path] = set()
    unique: list[Path] = []
    for file in sorted(files, key=lambda item: (item.name.casefold(), str(item).casefold())):
        resolved = file.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(file)
    return unique


def read_source(
    path: Path,
    *,
    sheet: str | None = None,
    period: int | None = None,
) -> SourceDocument:
    """Lee y clasifica una fuente mensual; no modifica el archivo."""

    if not path.is_file():
        raise FileNotFoundError(f"No existe la fuente: {path}")
    if path.name.startswith("~$"):
        raise SourceNotRecognized(f"Archivo de bloqueo de Excel: {path.name}")
    if path.suffix.casefold() not in ALLOWED_SUFFIXES:
        raise SourceNotRecognized(f"Sufijo no admitido: {path.name}")

    if path.suffix.casefold() == ".csv":
        sheet_name = path.stem
        rows = _read_csv(path)
    else:
        sheet_name, rows = _read_xlsx(path, sheet)

    if looks_like_wide_matrix(rows):
        raise SourceNotRecognized(
            f"{path.name!r} usa una matriz ancha de indicadores, sin columna de "
            "ejecución apilada; no es un corte mensual normalizable"
        )

    if count_atomic_labels(rows) == 0:
        raise SourceNotRecognized(
            f"{path.name!r} no contiene indicadores atómicos reconocibles del catálogo"
        )

    period_value, evidence = _infer_period(path, rows, sheet_name, period)
    cut = infer_cut_date(path, rows, sheet_name, period_value)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return SourceDocument(
        path=path,
        sheet=sheet_name,
        rows=rows,
        period=period_value,
        cut_date=cut,
        layout="apilado",
        sha256=digest,
        period_evidence=evidence,
    )
