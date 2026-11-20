"""Errores de dominio del ETL.

La separación permite distinguir un archivo que no es un corte mensual
(se omite y se documenta) de una violación de contrato (se reporta como error).
"""

from __future__ import annotations


class ETLException(Exception):
    """Error base del ETL."""


class SourceNotRecognized(ETLException, ValueError):
    """La fuente no es un corte mensual reconocible.

    Se usa para archivos auxiliares, matrices sin ejecución o documentos que
    no permiten inferir el periodo. No es una violación de contrato: el lote
    continúa y el motivo queda en el manifiesto.
    """


class ContractViolation(AssertionError, ValueError):
    """Violación de una precondición, postcondición o invariante formal.

    Hereda también de ``ValueError`` para que los llamadores existentes que
    capturaban errores de datos sigan funcionando sin relajar el contrato.
    """


class PeriodConflict(ETLException):
    """Dos fuentes distintas reclaman el mismo periodo con hechos diferentes."""
