# ETL de Metas de Formación — SENA Centro ASTIN

Normalizador multitemporal, idempotente y verificable de los cortes mensuales de Metas de Formación del Centro Nacional de Asistencia Técnica a la Industria (ASTIN), Regional Valle.

El resultado principal es **un libro Excel por periodo** con una tabla de hechos atómica en 1FN y las dimensiones de un esquema en estrella, listo para Power BI. Opcionalmente se emite también el CSV canónico de seis columnas para mantener compatibilidad con consultas Power Query existentes.

## Tabla de hechos canónica

```text
FactMetas = (IdCentro, IdPeriodo, IdCategoria, IdNivelFormación, Meta, Ejecución)
```

- `IdCentro = 1` para ASTIN.
- `IdPeriodo = YYYYMM` (por ejemplo `202605`).
- `IdCategoria` e `IdNivelFormación` son claves foráneas a `DimCategoria` y `DimNivelFormación`.
- `Meta` y `Ejecución` son enteros no negativos.
- La clave compuesta `(IdCentro, IdPeriodo, IdCategoria, IdNivelFormación)` es única.
- No se almacenan subtotales, porcentajes, retención ni certificación.

## Libro mensual

Cada archivo `Modelo_Normalizado_Metas_Centro_ASTIN_YYYY_MM.xlsx` contiene:

| Hoja | Contenido |
|---|---|
| `FactMetas` | Hechos atómicos, exactamente seis columnas |
| `DimCentro` | Centro, código, nombre y regional |
| `DimPeriodo` | Periodo, año, mes, nombre del mes y fecha de corte |
| `DimCategoria` | Categorías canónicas del catálogo |
| `DimNivelFormación` | Niveles y modalidades del catálogo |
| `DimIndicador` | Catálogo completo de 28 indicadores atómicos |
| `Control` | Fuente, hoja, hashes, sumas, total reportado, deltas y estado de conciliación |

La hoja `Control` permite auditar qué archivo y qué hoja alimentaron el periodo, y deja visible cualquier diferencia entre la suma atómica y el total de cabecera de la fuente.

El libro **no** incluye la columna `Porcentaje` del libro de referencia. El porcentaje de cumplimiento es una medida DAX (`DIVIDE([Ejecucion_Total], [Meta_Total], 0)`) y no debe mezclarse con conteos de personas.

## Origen de los datos

Fuente operativa solicitada:

```text
C:\Users\capatino\Desktop\Metas de formación\Metas 2026
```

Destino de los libros normalizados:

```text
C:\Users\capatino\OneDrive - Servicio Nacional de Aprendizaje\BACKUP DISCO\Mis proyectos\AREA LABORAL\SENA\POWER BI\Sistema de control e información - Estado de las metas centro ASTIN\01_Metas_Normalizadas
```

El proyecto también conserva cortes de referencia en `Metas/`. La ejecución final de la serie 2026 usa ambas carpetas: los cortes de abril, agosto, septiembre y octubre se leen del escritorio y mayo se completa con el corte del proyecto. Los duplicados idénticos del mismo periodo se registran en el manifiesto y no se reprocesan.

### Familias de formato soportadas

1. **Abril–mayo:** tabla apilada con columnas `Meta`, `Ejecución`, `% Ejecución`; los subtotales se identifican por `TOTAL`, `=` y prefijos de sección.
2. **Agosto–octubre:** tabla apilada `INDICADOR`, `Meta 2026`, `Ejecución`, `% Ejecución`, `Estado`; los totales de cabecera se leen solo para conciliación.
3. **Libros con varias hojas:** se elige la hoja con el corte más reciente inferible. En el libro de abril se selecciona `30 ABRIL`, no `20 ABRIL`. `--sheet` permite forzar una hoja.
4. **Matrices anchas sin ejecución:** se omiten con motivo explícito. Es el caso de `METAS FORMACION 2026 - TAYANA.xlsx`, que contiene metas en una fila y no una columna de ejecución apilada.

## Ejecución

```powershell
python -m pip install -r requirements.txt

# Serie completa: escritorio + mayo del proyecto
python run_etl.py `
  "C:\Users\capatino\Desktop\Metas de formación\Metas 2026" `
  "Metas" `
  --output "C:\Users\capatino\OneDrive - Servicio Nacional de Aprendizaje\BACKUP DISCO\Mis proyectos\AREA LABORAL\SENA\POWER BI\Sistema de control e información - Estado de las metas centro ASTIN\01_Metas_Normalizadas" `
  --format both --period-policy latest
```

Sin argumentos se usa la carpeta de origen por defecto de `metas_etl/config.py` y se emiten libros `.xlsx`:

```powershell
python run_etl.py --format xlsx
```

Ese comando procesa solo `Desktop\Metas de formación\Metas 2026` (cuatro periodos). Para incluir mayo, pasa también `Metas` como en el ejemplo anterior.

Opciones principales:

| Opción | Efecto |
|---|---|
| `--format xlsx\|csv\|both` | Formato de salida; `xlsx` es el predeterminado |
| `--period-policy error\|latest` | Conflicto de mismo periodo: fallar o elegir el corte más reciente |
| `--sheet NOMBRE` | Hoja explícita; solo con una fuente |
| `--period YYYYMM` | Periodo explícito; solo con una fuente |
| `--strict` | Falla si hay fuentes omitidas además de errores |
| `--fail-on-delta` | No escribe periodos cuya suma atómica no cuadre con el total reportado |
| `--control-output RUTA` | Carpeta alternativa para el manifiesto |

El manifiesto determinista queda en `control_metas/manifiesto_metas.json` e incluye `procesados`, `omitidos`, `duplicados`, `errores`, hashes y resumen.

## Reglas de calidad

- Los valores vacíos, guiones y `NaN` se convierten en `0`.
- Los porcentajes, fechas, letras y cantidades fraccionarias se rechazan como cantidades.
- Los puntos de miles y la coma decimal se interpretan en formato español.
- Las filas de total, subtotal, balance o sección no se emiten.
- Las etiquetas desconocidas no se aproximan: se descartan.
- La tabla de hechos es dispersa: solo contiene los indicadores que aparecen en el corte. Un indicador ausente no se convierte en cero.
- La escritura es atómica y el libro se verifica contra el contrato antes de reemplazar el destino.
- Dos ejecuciones con las mismas fuentes producen exactamente los mismos bytes de salida y el mismo manifiesto.

## Conciliación de totales 2026

| Periodo | Δ Meta | Δ Ejecución | Interpretación |
|---|---:|---:|---|
| 2026-04 | 0 | 0 | Cuadra |
| 2026-05 | 0 | 0 | Cuadra |
| 2026-08 | +90 | +98 | Diferencia de la fuente |
| 2026-09 | +90 | +98 | Diferencia de la fuente |
| 2026-10 | +90 | +57 | Diferencia de la fuente |

La diferencia es del reporte fuente, no del ETL. La suma de las filas atómicas coincide exactamente con la tabla normalizada. El total de cabecera de la familia agosto–octubre no incorpora de forma consistente todas las filas de las estrategias CampeSENA/Full Popular. El ETL no ajusta la diferencia: la deja visible en `Control` y en el manifiesto.

## Catálogo

El catálogo contiene 28 pares `(IdCategoria, IdNivelFormación)`:

- 21 pares de la tabla de la especificación formal.
- 7 pares de la extensión técnica autorizada para formación complementaria regular virtual/presencial, placa huella, otros programas FEC, complementaria CampeSENA, complementaria Full Popular y FEP.

Los pares adicionales son `(4,15)`, `(4,16)`, `(3,17)`, `(3,18)`, `(10,19)`, `(1,20)` y `(1,21)`.

> **Nota de consistencia:** la hoja `DimCategoria` del libro de referencia `Modelo_Normalizado_Metas_Centro_ASTIN_Mayo2026.xlsx` usa una numeración secuencial distinta a la especificación formal. Este proyecto usa la numeración de la especificación: `1 = Full Popular`, `3 = FIC`, `4 = Formación regular`, `10 = CampeSENA`, `16 = Articulación con la Media`. Ver `docs/MODELO_DIMENSIONAL.md`.

## Pruebas

```powershell
python -m pytest -q
python -m ruff check metas_etl tests
```

La suite cubre:

- parsing de cantidades y rechazo de porcentajes/fracciones;
- catálogo y contratos de las seis columnas;
- normalización de las dos familias de formato;
- purga de subtotales y conservación atómica;
- propiedades con Hypothesis;
- estructura, dimensiones y bytes idénticos del libro Excel;
- políticas de duplicados, conflictos de periodo y `--fail-on-delta`;
- regresión contra los cortes reales de `Metas/` y de `Desktop\Metas 2026` cuando están presentes.

Las fuentes reales se leen en modo de solo lectura y las pruebas se omiten si las carpetas no existen. No se copian archivos operativos a fixtures ni a Git.

## Estructura del proyecto

```text
metas_etl/
  catalog.py        Catálogo, dimensiones y normalización de etiquetas
  rules.py           Parsing, filtrado de subtotales y extracción atómica
  io.py              Descubrimiento, lectura CSV/XLSX e inferencia de periodo
  normalize.py       Contratos de Hoare y construcción de hechos
  workbook.py        Libro Excel, dimensiones, control y serialización determinista
  persist.py         Escritura atómica de XLSX/CSV/JSON
  cli.py             Orquestación del lote y manifiesto
docs/
  ESPECIFICACION_FORMAL.md
  MODELO_DIMENSIONAL.md
tests/
```

## Documentación adicional

- `docs/ESPECIFICACION_FORMAL.md`: precondiciones, postcondiciones, invariantes de ciclo, prueba de idempotencia y matriz de pruebas.
- `docs/MODELO_DIMENSIONAL.md`: esquema en estrella, relaciones, medidas DAX y consulta Power Query para el libro mensual.
- `docs/Analisis_Brecha_Especificaciones_Mayo2026.docx`: análisis de la diferencia entre la fuente original de mayo, el libro de referencia y la salida actual; contiene la propuesta de modificación de especificaciones sujeta a aprobación.
- `docs/RESUMEN_ACTIVIDADES_NOVIEMBRE_2026.md`: resumen de las actividades de desarrollo, entregables, validaciones y pendientes de noviembre de 2026.
- `AGENTS.md`: reglas de contribución del repositorio.
