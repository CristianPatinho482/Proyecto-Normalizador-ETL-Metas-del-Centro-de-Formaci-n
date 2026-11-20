"""Persistencia atómica, determinista e idempotente.

La escritura usa un temporal en el mismo directorio del destino y ``os.replace``
para que un lector nunca observe un archivo parcial. Los CSV se escriben en
UTF-8 sin BOM y con salto de línea ``\n``. Los XLSX se construyen en memoria,
se verifican contra el contrato y solo entonces se reemplazan.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path

from .normalize import FIELDS


def _filesystem_path(path: Path) -> str:
    """Devuelve una ruta apta para la API de Windows, con prefijo extendido.

    El destino institucional de OneDrive se acerca al límite histórico de 260
    caracteres. El prefijo ``\\\\?\\`` evita que el temporal corto o el rename
    fallen por longitud.
    """

    resolved = str(path.resolve())
    if os.name != "nt" or len(resolved) < 240 or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def atomic_bytes(path: Path, data: bytes) -> None:
    """Escribe ``data`` en ``path`` de forma atómica."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".etl-", suffix=path.suffix, dir=_filesystem_path(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, _filesystem_path(path))
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def csv_bytes(rows: list[dict[str, object]], fields: tuple[str, ...] = FIELDS) -> bytes:
    """Serializa hechos canónicos sin BOM y con separador punto y coma."""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def atomic_csv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...] = FIELDS) -> None:
    atomic_bytes(path, csv_bytes(rows, fields))


def write_fact(path: Path, rows: list[dict[str, int]]) -> None:
    """Escribe la tabla de hechos canónica en CSV."""

    atomic_csv(path, rows, FIELDS)


def write_json(path: Path, value: object) -> None:
    """Escribe un manifiesto JSON determinista (claves ordenadas)."""

    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_bytes(path, text.encode("utf-8"))
