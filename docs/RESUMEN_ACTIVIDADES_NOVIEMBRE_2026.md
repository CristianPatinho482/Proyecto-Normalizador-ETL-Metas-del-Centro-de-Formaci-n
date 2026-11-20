# Resumen de actividades de desarrollo — Noviembre 2026

**Proyecto:** Normalizador ETL multitemporal de Metas de Formación — SENA Centro ASTIN  
**Periodo del resumen:** noviembre de 2026  
**Estado:** implementación v2.0.0 completada y validada; ampliación de alcance pendiente de aprobación

---

## 1. Resumen ejecutivo

Durante noviembre se evolucionó el proyecto desde un ETL que generaba únicamente CSV de hechos hacia una solución completa de normalización multitemporal con:

- lectura de fuentes CSV y Excel;
- selección determinista de hojas y periodos;
- normalización estricta de las dos familias de reportes (abril–mayo y agosto–octubre);
- generación de un **libro Excel mensual** con tabla de hechos en 1FN y esquema en estrella;
- verificación del libro antes de la escritura atómica;
- idempotencia comprobada a nivel de bytes;
- suite de pruebas con cobertura de contratos, propiedades, lotes y fuentes reales;
- documentación formal y modelo dimensional;
- análisis específico de la brecha del corte de mayo frente al libro de referencia.

Se generaron los libros de **abril, mayo, agosto, septiembre y octubre de 2026** en la carpeta institucional de OneDrive, con sus CSV canónicos equivalentes.

---

## 2. Hitos del mes

| Fecha | Hito | Resultado |
|---|---|---|
| 6 nov. | Implementación de la versión 2.0.0 | Nuevos módulos de reglas, configuración, errores, libro Excel y CLI ampliada |
| 6 nov. | Validación inicial | 31 pruebas aprobadas y `ruff` sin hallazgos |
| 6 nov. | Primera generación multitemporal | Cinco periodos procesados; un archivo omitido y cuatro duplicados controlados |
| 13 nov. | Análisis de brecha de mayo | Documento Word con la diferencia entre fuente, referencia y salida del ETL |
| 20 nov. | Consolidación del resumen | Estado del proyecto, entregables y decisiones pendientes documentados |

---

## 3. Actividades de desarrollo

### 3.1 Arquitectura y organización del código

Se separaron responsabilidades en módulos independientes:

| Módulo | Responsabilidad |
|---|---|
| `metas_etl/catalog.py` | Catálogo de 28 indicadores atómicos, categorías, niveles y normalización de etiquetas |
| `metas_etl/rules.py` | Parsing de cantidades, detección de subtotales, extracción de filas atómicas y detección de matrices anchas |
| `metas_etl/io.py` | Descubrimiento de fuentes, lectura CSV/XLSX, selección de hoja, inferencia de periodo y fecha de corte |
| `metas_etl/normalize.py` | Contratos de Hoare, construcción de hechos, validación y conciliación |
| `metas_etl/workbook.py` | Construcción del libro Excel, dimensiones, hoja de control, serialización determinista y verificación |
| `metas_etl/persist.py` | Escritura atómica de XLSX, CSV y JSON; soporte de rutas largas de Windows/OneDrive |
| `metas_etl/cli.py` | Orquestación del lote, políticas de duplicados, manifiesto y resumen por consola |
| `metas_etl/config.py` | Rutas por defecto, centro ASTIN y nombres de meses |
| `metas_etl/errors.py` | Errores de dominio: fuente no reconocida, conflicto de periodo y violación de contrato |

### 3.2 Lectura y extracción

- Descubrimiento no recursivo de archivos `.csv`, `.xlsx` y `.xlsm`.
- Exclusión de bloqueos de Excel (`~$`) y de salidas del propio ETL.
- Lectura de Excel en modo solo lectura y sin enlaces externos.
- Selección de hoja por evidencia: cantidad de indicadores, periodo y fecha de corte.
- En el libro de abril se selecciona correctamente `30 ABRIL`, no `20 ABRIL`.
- Inferencia de periodo por nombre de archivo, título de hoja o encabezado.
- Inferencia de fecha de corte; si no hay día explícito, se usa el último día del mes.
- Detección y omisión explícita de matrices anchas sin columna de ejecución, como `METAS FORMACION 2026 - TAYANA.xlsx`.

### 3.3 Normalización y reglas de negocio

- Normalización de las dos familias de formato del reporte.
- Purga de filas de total, subtotal, balance, retención, certificación y secciones no aditivas.
- Cierre de la sección FPI en `TOTAL FORMACION COMPLEMENTARIA`.
- Frontera de respaldo por encabezados de sección cuando la fuente depurada eliminó el total.
- Parseo de cantidades en formato español:
  - `1.523` → `1523`;
  - `1.523.456` → `1523456`;
  - `1.523,00` → `1523`;
  - `-`, vacío y `NaN` → `0`.
- Rechazo de porcentajes, fechas, letras y cantidades fraccionarias.
- Uso de posiciones de celda para conservar una ejecución vacía como `0` y no correr los valores.
- Validación de clave compuesta única y cantidades no negativas.
- Conciliación entre suma atómica y total reportado, sin ajustar diferencias de la fuente.

### 3.4 Libro Excel mensual

Se implementó el libro `Modelo_Normalizado_Metas_Centro_ASTIN_YYYY_MM.xlsx` con:

| Hoja | Contenido |
|---|---|
| `FactMetas` | Tabla atómica de seis columnas |
| `DimCentro` | Centro, código, nombre y regional |
| `DimPeriodo` | Periodo, año, mes, nombre del mes y fecha de corte |
| `DimCategoria` | Categorías canónicas de FPI |
| `DimNivelFormación` | Niveles y modalidades |
| `DimIndicador` | Catálogo de 28 indicadores atómicos |
| `Control` | Fuente, hoja, hashes, sumas, totales reportados, deltas y estado de conciliación |

Características adicionales:

- Tablas de Excel con estilo, filtros y encabezados fijos.
- Formatos numéricos para identificadores y cantidades.
- Fechas de corte con formato ISO.
- Sin columna `Porcentaje` en la tabla de hechos.
- Verificación de estructura, encabezados, filas, dimensiones y hashes antes de escribir.
- Serialización XLSX determinista: fechas ZIP fijas y `docProps` normalizados.
- Escritura atómica con temporal corto y soporte de rutas largas.

### 3.5 CLI y operación

Se amplió la interfaz de línea de comandos con:

- múltiples fuentes de entrada;
- `--format xlsx|csv|both`;
- `--period-policy error|latest`;
- `--sheet` y `--period` para fuentes individuales;
- `--strict` para fallar ante fuentes omitidas;
- `--fail-on-delta` para bloquear periodos no conciliados;
- `--quiet`;
- manifiesto determinista en `control_metas/manifiesto_metas.json`.

También se implementó:

- agrupación por periodo;
- detección de duplicados idénticos;
- conflicto de periodo con hechos distintos;
- política `latest` para elegir el corte más reciente;
- resumen de procesados, omitidos, duplicados y errores.

### 3.6 Calidad y pruebas

Se crearon y actualizaron pruebas para:

- parsing de cantidades y rechazo de formatos inválidos;
- catálogo y contratos de las seis columnas;
- purga de subtotales y conservación atómica;
- normalización de las dos familias de formato;
- propiedades con Hypothesis;
- estructura y contenido del libro Excel;
- idempotencia de bytes;
- políticas de duplicados y conflictos;
- `--strict` y `--fail-on-delta`;
- regresión contra los cortes reales de `Metas/` y `Desktop\Metas 2026`.

### 3.7 Documentación

Se actualizaron o crearon:

- `README.md`: uso, salidas, reglas, conciliación y estructura del proyecto.
- `AGENTS.md`: reglas de contribución.
- `docs/ESPECIFICACION_FORMAL.md`: precondiciones, postcondiciones, invariantes, idempotencia y matriz de pruebas.
- `docs/MODELO_DIMENSIONAL.md`: esquema en estrella, relaciones, medidas DAX y Power Query.
- `docs/Analisis_Brecha_Especificaciones_Mayo2026.docx`: análisis de la diferencia de alcance del corte de mayo.

---

## 4. Entregables generados

### 4.1 Libros y CSV normalizados

Carpeta:

```text
C:\Users\capatino\OneDrive - Servicio Nacional de Aprendizaje\BACKUP DISCO\Mis proyectos\AREA LABORAL\SENA\POWER BI\Sistema de control e información - Estado de las metas centro ASTIN\01_Metas_Normalizadas
```

| Periodo | Libro | Filas | Meta | Ejecución | Conciliación |
|---|---|---:|---:|---:|---|
| 2026-04 | `Modelo_Normalizado_Metas_Centro_ASTIN_2026_04.xlsx` | 28 | 31.733 | 13.974 | CUADRA |
| 2026-05 | `Modelo_Normalizado_Metas_Centro_ASTIN_2026_05.xlsx` | 28 | 31.733 | 15.505 | CUADRA |
| 2026-08 | `Modelo_Normalizado_Metas_Centro_ASTIN_2026_08.xlsx` | 20 | 31.823 | 25.379 | DIFERENCIA_FUENTE (+90 / +98) |
| 2026-09 | `Modelo_Normalizado_Metas_Centro_ASTIN_2026_09.xlsx` | 20 | 31.823 | 28.695 | DIFERENCIA_FUENTE (+90 / +98) |
| 2026-10 | `Modelo_Normalizado_Metas_Centro_ASTIN_2026_10.xlsx` | 20 | 31.823 | 30.103 | DIFERENCIA_FUENTE (+90 / +57) |

También se generaron los CSV canónicos equivalentes.

### 4.2 Manifiesto de control

```text
control_metas\manifiesto_metas.json
```

Contiene:

- periodos procesados;
- fuentes y hojas utilizadas;
- hashes SHA-256;
- sumas atómicas;
- totales reportados;
- diferencias;
- estado de conciliación;
- archivos omitidos;
- duplicados;
- errores.

### 4.3 Documento de análisis de brecha

```text
docs\Analisis_Brecha_Especificaciones_Mayo2026.docx
```

Copia en escritorio:

```text
C:\Users\capatino\Desktop\Metas de formación\Analisis_Brecha_Especificaciones_Mayo2026.docx
```

---

## 5. Resultados de validación

| Validación | Resultado |
|---|---|
| `python -m pytest -q` | **31 pruebas aprobadas, 58 subpruebas** |
| `python -m ruff check metas_etl tests` | **Sin hallazgos** |
| Idempotencia de XLSX | Hashes idénticos entre ejecuciones |
| Idempotencia de CSV | Hashes idénticos entre ejecuciones |
| Idempotencia del manifiesto | Bytes idénticos entre ejecuciones |
| Lote de fuentes reales | 5 periodos, 1 omitido, 4 duplicados, 0 errores |
| Conciliación abril/mayo | 0 / 0 |
| Conciliación agosto/septiembre/octubre | Diferencias de fuente documentadas |

---

## 6. Análisis de brecha del corte de mayo

Se compararon tres archivos:

1. fuente original `METAS CENTRO ASTIN - CORTE 31 MAYO 2026.xlsx`;
2. libro de referencia `Modelo_Normalizado_Metas_Centro_ASTIN_Mayo2026.xlsx`;
3. salida del ETL `Modelo_Normalizado_Metas_Centro_ASTIN_2026_05.xlsx`.

### 6.1 Hallazgo

| Archivo | Filas | Composición |
|---|---:|---|
| Fuente original | 111 | 78 indicadores atómicos + 33 totales/subtotales |
| Libro de referencia | 112 | 78 atómicos + 34 totales (incluye un total derivado de bilingüismo) |
| Salida actual | 28 | Solo los 28 atómicos de FPI |

Faltan **50 indicadores atómicos** en la salida actual:

| Sección | Faltantes |
|---|---:|
| Retención | 10 |
| Certificación Formación Profesional | 5 |
| Certificación de Competencias Laborales | 15 |
| Poblaciones Vulnerables | 2 |
| Desagregación Poblaciones Vulnerables | 14 |
| Emprendimiento y Fortalecimiento | 2 |
| Contratos de Aprendizaje | 2 |
| **Total** | **50** |

### 6.2 Conclusión

La salida actual es correcta para el alcance FPI definido en la especificación vigente, pero no reproduce el contenido completo del libro de referencia. Para ello se requiere modificar la especificación y ampliar el modelo de datos.

El libro de referencia no debe copiarse tal como está porque:

- incluye totales en la tabla de hechos;
- mezcla conteos con ratios y porcentajes;
- tiene 29 `IdIndicador` sin fila en `DimIndicador`;
- desalinea los `IdIndicador` 29–42;
- usa una numeración de categorías distinta a la especificación formal.

La propuesta recomendada es un modelo de dos tablas de hechos:

- `FactMetas` para los 28 indicadores FPI;
- `FactIndicadoresInstitucionales` para los 50 indicadores atómicos restantes;
- `FactTotalesReportados` opcional, no sumable, para conciliación.

---

## 7. Decisiones pendientes

1. Confirmar el alcance: solo FPI o reporte institucional completo.
2. Elegir el modelo: dos tablas de hechos, tabla generalizada o replicar la referencia.
3. Definir si “Total Aprendices Primer Curso” es un KPI atómico o un total.
4. Definir si los 33 totales se conservan en una tabla separada o solo en `Control`.
5. Definir la numeración de categorías para las nuevas secciones.
6. Definir si los ratios se almacenan como decimal `0..1` o como porcentaje `0..100`.

---

## 8. Próximos pasos sugeridos

1. Aprobar el alcance y la opción de modelo.
2. Actualizar formalmente `ESPECIFICACION_FORMAL.md` y `MODELO_DIMENSIONAL.md`.
3. Ampliar el catálogo a los 78 indicadores atómicos.
4. Implementar el parsing de ratios y la separación por tipo de valor.
5. Agregar `FactIndicadoresInstitucionales` y, si se aprueba, `FactTotalesReportados`.
6. Ampliar la suite de pruebas y la regresión de mayo.
7. Actualizar el modelo de Power BI y las medidas DAX.
8. Regenerar los libros de todos los meses.

---

## 9. Riesgos y observaciones

- **Diferencia de fuente en agosto–octubre:** los totales de cabecera no coinciden con la suma de hojas atómicas. La diferencia se documenta, no se ajusta.
- **Fuente depurada:** un archivo sin total reportado puede normalizarse, pero si eliminó filas atómicas el ETL no puede detectarlo; se recomienda usar los cortes completos.
- **Matriz ancha:** `METAS FORMACION 2026 - TAYANA.xlsx` se omite porque no tiene ejecución apilada. No se imputa ejecución cero.
- **Tabla dispersa:** un indicador ausente no se convierte en cero; ausencia y cero no son equivalentes.
- **Rutas largas:** la carpeta de OneDrive se acerca al límite histórico de Windows; la escritura atómica ya usa prefijo extendido y temporales cortos.
- **Compatibilidad:** cualquier cambio de nombre o de columnas de `FactMetas` debe coordinarse con las consultas Power Query existentes.

---

**Elaborado:** 20 de noviembre de 2026  
**Proyecto:** `C:\Users\capatino\Documents\Proyecto Normalizador ETL Metas del Centro de Formación`
