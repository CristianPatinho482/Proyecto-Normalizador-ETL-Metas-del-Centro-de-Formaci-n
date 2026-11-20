"""Reglas puras de parsing, filtrado y extracción de filas atómicas.

Este módulo no lee archivos ni escribe resultados. Concentra las funciones
que se usan tanto en la lectura (para puntuar hojas) como en la normalización,
evitando dependencias circulares.

Contratos relevantes
--------------------
``parse_int``
    Pre:  ``value`` es un escalar o texto.
    Post: retorna un ``int``; ``None``, vacío, guion y NaN se mapean a 0;
          porcentajes, fechas, letras y fracciones se rechazan con ValueError.

``is_subtotal_label``
    Post: True si la etiqueta representa un agregado de balance, una sección
          no cuantitativa o una fila de total. Los marcadores de una letra
          entre paréntesis no bastan por sí solos: ``(M)`` y ``(S)`` son
          indicadores atómicos en la familia de abril/mayo.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

from .catalog import ALIAS_TO_INDICATOR, norm

# Prefijos de secciones que nunca contienen hechos atómicos. Se comparan
# contra el texto normalizado, no contra el texto original.
_NON_ATOMIC_PREFIXES = (
    "total",
    "formacion titulada",
    "formacion profesional integral",
    "formacion tecnologica",
    "formacion ocupacional",
    "retencion",
    "certificacion",
    "poblaciones vulnerables",
    "desagregacion",
    "emprendimiento",
    "contratos de aprendizaje",
    "metas programas relevantes",
    "aprendices de primer curso",
)


def parse_int(value: object) -> int:
    """Convierte una cantidad institucional a entero no negativo.

    Acepta el formato español de miles (``1.523``), el formato con coma
    decimal (``1.523,00``) y valores numéricos de Excel. Rechaza porcentajes,
    fechas, texto y cantidades fraccionarias para evitar que un ratio de
    retención se confunda con un conteo de personas.
    """

    if value is None:
        return 0
    if isinstance(value, bool):
        raise TypeError(f"Un booleano no es una cantidad: {value!r}")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError(f"La cantidad debe ser entera: {value!r}")
        return int(value)
    if isinstance(value, float):
        if math.isnan(value):
            return 0
        if math.isinf(value):
            raise ValueError(f"Cantidad no finita: {value!r}")
        if not value.is_integer():
            raise ValueError(f"La cantidad debe ser entera: {value!r}")
        return int(value)

    raw = str(value).strip().replace("\xa0", "").replace(" ", "")
    if raw.casefold() in {"", "-", "—", "–", "nan", "null", "none"}:
        return 0
    if raw.endswith("%"):
        raise ValueError(f"Un porcentaje no es una cantidad: {value!r}")

    # Solo se admiten dígitos, separadores y signo. Esto excluye fechas,
    # texto y símbolos que antes podían colarse al eliminar caracteres.
    if not re.fullmatch(r"[+-]?[0-9.,]+", raw):
        raise ValueError(f"Cantidad no numérica: {value!r}")

    negative = raw.startswith("-")
    if raw[:1] in "+-":
        raw = raw[1:]
    if not raw:
        raise ValueError(f"Cantidad no numérica: {value!r}")

    if raw.count(",") > 1:
        raise ValueError(f"Formato numérico ambiguo: {value!r}")

    if "," in raw:
        if "." in raw:
            # Formato español: 1.523,00. El punto debe preceder a la coma.
            if raw.rfind(".") > raw.rfind(","):
                raise ValueError(f"Formato numérico ambiguo: {value!r}")
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", ".")
    elif raw.count(".") > 1:
        if not re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
            raise ValueError(f"Formato numérico ambiguo: {value!r}")
        raw = raw.replace(".", "")
    elif "." in raw and re.fullmatch(r"\d{1,3}\.\d{3}", raw):
        # 1.523 es separador de miles, no decimal.
        raw = raw.replace(".", "")

    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Cantidad no numérica: {value!r}") from exc
    if number != number.to_integral_value():
        raise ValueError(f"La cantidad debe ser entera: {value!r}")
    result = int(number)
    return -result if negative else result


def is_subtotal_label(label: object) -> bool:
    """True si la etiqueta es un agregado, sección o fila de total."""

    text = str(label or "").strip()
    if not text:
        return True
    if "=" in text:
        return True
    normalized = norm(text)
    if not normalized:
        return True
    if "total" in normalized.split():
        return True
    return normalized.startswith(_NON_ATOMIC_PREFIXES)


def is_total_complementaria(row: list[object]) -> bool:
    """True en la fila que cierra la sección FPI antes de retención.

    La fila ``TOTAL FORMACION COMPLEMENTARIA`` separa los hechos aditivos de
    los tableros de retención, certificación y población vulnerable. La
    variante ``Total Formación Complementaria Estrategia ...`` no cierra la
    sección porque es un subtotal intermedio.
    """

    first = next((norm(cell) for cell in row if str(cell or "").strip()), "")
    return first.startswith("total formacion complementaria") and "estrategia" not in first


_SECTION_STOPS = (
    "metas programas relevantes",
    "aprendices de primer curso",
    "retencion",
    "certificacion",
    "poblaciones vulnerables",
    "desagregacion otras poblaciones",
    "emprendimiento y fortalecimiento",
    "contratos de aprendizaje",
)


def is_non_atomic_section(row: list[object]) -> bool:
    """True en encabezados de tableros que repiten etiquetas no aditivas.

    Sirve como frontera de respaldo cuando la fuente depurada eliminó la fila
    ``TOTAL FORMACION COMPLEMENTARIA`` pero conservó retención, certificación
    o poblaciones vulnerables.
    """

    first = next((norm(cell) for cell in row if str(cell or "").strip()), "")
    return first.startswith(_SECTION_STOPS)



def extract_atomic(row: list[object]) -> tuple[str, object, object] | None:
    """Extrae ``(etiqueta, meta_cruda, ejecucion_cruda)`` de una fila atómica.

    La etiqueta se busca en cualquier celda no vacía y los dos valores se
    toman posicionalmente a su derecha. Usar posiciones, en lugar de la lista
    de celdas no vacías, preserva una ejecución vacía como 0 y evita correr
    los valores cuando el reporte deja una celda en blanco.
    """

    cells = [str(value).strip() if value is not None else "" for value in row]
    nonempty = [(index, value) for index, value in enumerate(cells) if value]
    if len(nonempty) < 2:
        return None
    for index, label in nonempty:
        if is_subtotal_label(label):
            continue
        indicator = ALIAS_TO_INDICATOR.get(norm(label))
        if indicator is None:
            continue
        meta = row[index + 1] if index + 1 < len(row) else None
        ejecucion = row[index + 2] if index + 2 < len(row) else None
        return label, meta, ejecucion
    return None


def count_atomic_labels(rows: list[list[object]]) -> int:
    """Cuenta filas con una etiqueta atómica antes del cierre de FPI.

    Se usa para puntuar hojas de un libro con varios cortes. No valida los
    valores; solo mide la evidencia estructural de que la hoja es un corte.
    """

    count = 0
    for row in rows:
        if is_total_complementaria(row) or (count and is_non_atomic_section(row)):
            break
        if extract_atomic(row) is not None:
            count += 1
    return count


def looks_like_wide_matrix(rows: list[list[object]]) -> bool:
    """Detecta una matriz ancha (encabezados en fila y valores en otra).

    La fuente ``METAS FORMACION 2026 - TAYANA.xlsx`` tiene decenas de
    indicadores en una fila de encabezado y una sola fila de metas, sin
    columna de ejecución. No es un corte mensual apilado y debe omitirse,
    no interpretarse como hechos con ejecución cero.
    """

    for row in rows:
        labels = sum(
            1
            for cell in row
            if str(cell or "").strip()
            and not is_subtotal_label(cell)
            and norm(cell) in ALIAS_TO_INDICATOR
        )
        if labels >= 5:
            return True
    return False
