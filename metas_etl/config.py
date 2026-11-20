"""Parámetros institucionales y rutas por defecto del proyecto.

Las rutas se pueden reemplazar con las variables de entorno
``METAS_SOURCE_DIR`` y ``METAS_OUTPUT_DIR`` o con los argumentos de la CLI.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SOURCE = Path(
    os.environ.get(
        "METAS_SOURCE_DIR",
        r"C:\Users\capatino\Desktop\Metas de formación\Metas 2026",
    )
)

DEFAULT_OUTPUT = Path(
    os.environ.get(
        "METAS_OUTPUT_DIR",
        r"C:\Users\capatino\OneDrive - Servicio Nacional de Aprendizaje"
        r"\BACKUP DISCO\Mis proyectos\AREA LABORAL\SENA\POWER BI"
        r"\Sistema de control e información - Estado de las metas centro ASTIN"
        r"\01_Metas_Normalizadas",
    )
)

DEFAULT_CONTROL = PROJECT_ROOT / "control_metas"

ID_CENTRO_ASTIN = 1

CENTER = {
    "IdCentro": ID_CENTRO_ASTIN,
    "CodigoCentro": 9230,
    "NombreCentro": "CENTRO NACIONAL DE ASISTENCIA TECNICA A LA INDUSTRIA - ASTIN",
    "Regional": "VALLE",
}

MONTH_NAMES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}
