"""Catálogo determinista de indicadores atómicos y dimensiones del reporte.

El catálogo es la función total ``M_dim`` de la especificación formal:
asigna a cada etiqueta atómica un par ``(IdCategoria, IdNivelFormación)``.
Las etiquetas desconocidas no se inventan ni se aproximan: se descartan.

Los primeros 21 pares provienen de la tabla de la especificación formal.
Los siete pares adicionales son la extensión técnica autorizada para las
hojas de formación complementaria, FEC, CampeSENA, Full Popular y FEP.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SCHEMA_VERSION = "FactMetas_v1"


def norm(text: object) -> str:
    """Normaliza una etiqueta para compararla de forma determinista."""

    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("\xa0", " ").casefold()
    value = re.sub(r"\([^)]*\)", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


@dataclass(frozen=True)
class Indicator:
    label: str
    id_categoria: int
    id_nivel: int
    aliases: tuple[str, ...] = ()


# Pares (IdCategoria, IdNivelFormación) de la especificación formal.
INDICATORS = (
    Indicator("Tecnólogos Regular - Presencial", 4, 4, ("Tecnólogos - Presencial",)),
    Indicator("Tecnólogos Regular - Virtual", 4, 12, ("Tecnólogos - Virtual",)),
    Indicator("Tecnólogos Regular - A Distancia", 4, 13, ("Tecnólogos - A Distancia",)),
    Indicator("Tecnólogos CampeSENA", 10, 4, ("Tecnólogos - CampeSENA",)),
    Indicator("Tecnólogos Full Popular", 1, 4, ("Tecnólogos - Full Popular",)),
    Indicator("Tecnólogos FIC", 3, 4, ()),
    Indicator("Operarios Regular", 4, 2, ()),
    Indicator("Operarios CampeSENA", 10, 2, ()),
    Indicator("Operarios Full Popular", 1, 2, ()),
    Indicator("Operarios FIC", 3, 2, ()),
    Indicator("Auxiliares Regular", 4, 1, ()),
    Indicator("Auxiliares CampeSENA", 10, 1, ()),
    Indicator("Auxiliares Full Popular", 1, 1, ()),
    Indicator(
        "Técnico Regular - Presencial y a Distancia",
        4,
        3,
        ("Técnico Regular - Presencial", "Técnico - Presencial"),
    ),
    Indicator("Técnico Regular - Virtual", 4, 14, ("Técnico - Virtual",)),
    Indicator("Técnico CampeSENA", 10, 3, ("Técnico - CampeSENA",)),
    Indicator("Técnico Full Popular", 1, 3, ("Técnico - Full Popular",)),
    Indicator(
        "Técnico Articulación con la Media",
        16,
        3,
        ("Técnico - Articulación Media", "Técnico - Articulación con la Media"),
    ),
    Indicator("Técnico FIC", 3, 3, ()),
    Indicator("Programa de Bilingüismo - Virtual", 4, 5, ()),
    Indicator("Programa de Bilingüismo - Presencial", 4, 6, ()),
    Indicator("Formación Complementaria Regular - Virtual (Sin Bilingüismo)", 4, 15, ()),
    Indicator("Formación Complementaria Regular - Presencial (Sin Bilingüismo)", 4, 16, ()),
    Indicator(
        "Placa huella 6 (incluida en FEC) (Código programa especial 2435)",
        3,
        17,
        ("Placa huella 6",),
    ),
    Indicator(
        "Otros programas FEC (Códigos programa especial 2436-2437)",
        3,
        18,
        ("Otros programas FEC",),
    ),
    Indicator("Formación Complementaria CampeSENA", 10, 19, ()),
    Indicator("Formación Complementaria Full Popular", 1, 20, ()),
    Indicator("Formación Especial Popular (FEP)", 1, 21, ()),
)

# Dimensiones canónicas. Los identificadores provienen de la especificación
# formal y no de la hoja DimCategoria del libro de referencia, que usa una
# numeración secuencial distinta. Ver docs/MODELO_DIMENSIONAL.md.
CATEGORIES = (
    (1, "Full Popular"),
    (3, "FIC"),
    (4, "Formación regular"),
    (10, "CampeSENA"),
    (16, "Articulación con la Media"),
)

LEVELS = (
    (1, "Auxiliar"),
    (2, "Operario"),
    (3, "Técnico"),
    (4, "Tecnólogo"),
    (5, "Bilingüismo - Virtual"),
    (6, "Bilingüismo - Presencial"),
    (12, "Tecnólogo - Virtual"),
    (13, "Tecnólogo - A Distancia"),
    (14, "Técnico - Virtual"),
    (15, "Formación Complementaria Regular - Virtual (Sin Bilingüismo)"),
    (16, "Formación Complementaria Regular - Presencial (Sin Bilingüismo)"),
    (17, "Placa Huella 6 (FEC)"),
    (18, "Otros Programas FEC"),
    (19, "Formación Complementaria CampeSENA"),
    (20, "Formación Complementaria Full Popular"),
    (21, "Formación Especial Popular (FEP)"),
)

CATEGORIES_BY_ID = dict(CATEGORIES)
LEVELS_BY_ID = dict(LEVELS)

ALIAS_TO_INDICATOR: dict[str, Indicator] = {}
for _indicator in INDICATORS:
    for _value in (_indicator.label, *_indicator.aliases):
        _key = norm(_value)
        if _key in ALIAS_TO_INDICATOR and ALIAS_TO_INDICATOR[_key] != _indicator:
            raise RuntimeError(f"Alias de indicador duplicado: {_value}")
        ALIAS_TO_INDICATOR[_key] = _indicator

BY_KEY = {(indicator.id_categoria, indicator.id_nivel): indicator for indicator in INDICATORS}


def indicator_for(category: int, level: int) -> Indicator:
    """Devuelve el indicador del par canónico o falla si no existe."""

    try:
        return BY_KEY[(category, level)]
    except KeyError as exc:
        raise KeyError(f"Par no catalogado: ({category}, {level})") from exc


def validate_catalog() -> None:
    """Invariantes del catálogo, verificados al importar el módulo."""

    keys = [(indicator.id_categoria, indicator.id_nivel) for indicator in INDICATORS]
    if len(keys) != len(set(keys)):
        raise RuntimeError("El catálogo contiene claves atómicas duplicadas")
    if len(INDICATORS) != 28:
        raise RuntimeError("El catálogo ampliado debe contener exactamente 28 indicadores")
    for indicator in INDICATORS:
        if indicator.id_categoria not in CATEGORIES_BY_ID:
            raise RuntimeError(f"Categoría no definida: {indicator.id_categoria}")
        if indicator.id_nivel not in LEVELS_BY_ID:
            raise RuntimeError(f"Nivel no definido: {indicator.id_nivel}")
    if len(CATEGORIES) != len(CATEGORIES_BY_ID) or len(LEVELS) != len(LEVELS_BY_ID):
        raise RuntimeError("Las dimensiones contienen identificadores duplicados")


validate_catalog()
