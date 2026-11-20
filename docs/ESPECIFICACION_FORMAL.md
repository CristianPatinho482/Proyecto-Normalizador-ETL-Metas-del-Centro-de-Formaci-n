# Especificación formal del ETL de Metas de Formación — Centro ASTIN

> **Nota de alcance (13/11/2026).** La especificación vigente cubre 28 indicadores atómicos de Formación Profesional Integral. El análisis `Analisis_Brecha_Especificaciones_Mayo2026.docx` concluye que, para reproducir el contenido completo del libro de referencia de mayo, se requiere ampliar el alcance a 78 indicadores atómicos y separar conteos de ratios. La modificación está sujeta a aprobación; este documento describe el contrato actual.

**Versión:** 2.0.0  
**Esquema de salida:** `FactMetas_v1`  
**Destino:** capa Silver / esquema en estrella para Power BI  
**Método:** lógica de Hoare `{P} C {Q}`, diseño por contrato, invariantes de ciclo y verificación de postcondiciones en tiempo de ejecución.

---

## 1. Alcance

El sistema transforma planillas mensuales preagregadas de Metas de Formación del Centro Nacional de Asistencia Técnica a la Industria (ASTIN) en una relación atómica en Primera Forma Normal.

El resultado principal es un libro Excel por periodo:

```text
Modelo_Normalizado_Metas_Centro_ASTIN_YYYY_MM.xlsx
```

El libro contiene la tabla de hechos canónica, cuatro dimensiones, el catálogo de indicadores y una hoja de control. Opcionalmente se emite el CSV canónico de seis columnas.

### 1.1 Fuera de alcance

- Retención, certificación, poblaciones vulnerables, emprendimiento y contratos de aprendizaje como hechos aditivos.
- Porcentajes de cumplimiento almacenados en la tabla de hechos.
- Inferencia de ejecución cuando la fuente no la contiene.
- Corrección automática de diferencias del reporte fuente.
- Interpretación de matrices anchas sin columna de ejecución.

---

## 2. Dominio de entrada

Sea `F_raw` una fuente mensual. Para este proyecto:

```text
F_raw = <filas, hoja, metadatos>
```

donde `filas` es una secuencia de filas de celdas y `hoja` es la hoja seleccionada de un libro Excel o el nombre lógico de un CSV.

Se reconocen dos familias apiladas:

| Familia | Periodos | Columnas relevantes |
|---|---|---|
| A | Abril–mayo | `Etiqueta`, `Meta`, `Ejecución`, `% Ejecución` |
| B | Agosto–octubre | `INDICADOR`, `Meta 2026`, `Ejecución`, `% Ejecución`, `Estado` |

Además se admiten libros con varias hojas. En ese caso se selecciona la hoja con el corte más reciente inferible.

### 2.1 Evidencia de periodo

El periodo `YYYYMM` se infiere, en orden de prioridad, de:

1. `--period` explícito;
2. una fecha completa en el nombre del archivo;
3. una fecha completa en el título de la hoja;
4. una fecha completa en el encabezado, prefiriendo líneas de `actualización`, `última`, `corte` o `vigencia` y, entre ellas, la más reciente;
5. combinación de mes y año provenientes de nombre, hoja y encabezado.

Si no hay evidencia suficiente, la fuente se omite con `SourceNotRecognized`. No se asume el año en curso.

### 2.2 Evidencia de fecha de corte

La fecha de corte se infiere del nombre, la hoja y el encabezado. Si no hay día explícito se usa el último día del mes. El día se acota al último día válido del mes.

---

## 3. Dominio canónico de salida

```text
T_FactMetas ⊂ IdCentro × IdPeriodo × IdCategoria × IdNivelFormación × Meta × Ejecución
```

con:

```text
IdCentro        ∈ {1}
IdPeriodo       ∈ {YYYYMM | YYYY ∈ [2020, 2030], MM ∈ [1, 12]}
IdCategoria     ∈ {1, 3, 4, 10, 16}
IdNivelFormación ∈ {1, 2, 3, 4, 5, 6, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21}
Meta            ∈ ℕ₀
Ejecución       ∈ ℕ₀
```

Cada fila satisface:

```text
set(fila) = {IdCentro, IdPeriodo, IdCategoria, IdNivelFormación, Meta, Ejecución}
```

No hay campos adicionales, nulos, cadenas vacías ni valores fraccionarios.

---

## 4. Contratos de Hoare

Sea `C = normalizar(F_raw)`.

### 4.1 Precondiciones `P`

```text
P1. path existe ∧ path es legible ∧ path no es un bloqueo (~$)
P2. suffix(path) ∈ {.csv, .xlsx, .xlsm}
P3. periodo(F_raw) es inferible ∨ --period fue suministrado
P4. F_raw contiene al menos una etiqueta atómica del catálogo
P5. F_raw no es una matriz ancha sin columna de ejecución
P6. las cantidades atómicas son enteras y no negativas
P7. no hay dos filas atómicas con la misma clave compuesta
```

`P1` y `P2` se verifican al descubrir y leer. `P3`–`P5` se verifican en `read_source`. `P6` y `P7` se verifican durante el recorrido.

### 4.2 Postcondiciones `Q`

Tras una ejecución exitosa:

```text
Q1. Esquema: cada hecho tiene exactamente seis campos y todos son int.
Q2. Unicidad: la clave (IdCentro, IdPeriodo, IdCategoria, IdNivelFormación) es única.
Q3. No negatividad: Meta ≥ 0 ∧ Ejecución ≥ 0.
Q4. Pureza: no se emiten subtotales, porcentajes, retención ni certificación.
Q5. Conservación: Σ Meta = Σ Meta de hojas atómicas
                 Σ Ejecución = Σ Ejecución de hojas atómicas.
Q6. Reconciliación: si existe total reportado T,
                 Σ atómica − T = Δ
    y Δ se registra; no se ajusta la tabla de hechos.
Q7. Idempotencia: normalizar(F_raw) = normalizar(F_raw) en hechos y control.
Q8. Serialización: el libro contiene exactamente FactMetas + dimensiones + Control,
    con encabezados y filas verificados antes del reemplazo atómico.
```

`Q1`–`Q3` se verifican en `assert_contract`. `Q5`–`Q8` se verifican en `assert_normalization_postconditions` y `verify_workbook_bytes`.

### 4.3 Precondición de lote

```text
P_lote. ∀ periodo p: |{fuentes con periodo p}| = 1
        ∨ todas las fuentes de p tienen hechos idénticos
        ∨ period_policy = latest
```

Si se viola y `period_policy = error`, el lote registra un `PeriodConflict`, no escribe ese periodo y retorna código 1.

---

## 5. Invariantes

### 5.1 Invariantes de calidad

```text
I1. ∀ hecho h: type(h.Meta) = int ∧ type(h.Ejecución) = int
I2. ∀ hecho h: h.Meta ≥ 0 ∧ h.Ejecución ≥ 0
I3. ∀ hecho h: h.IdCentro = 1 ∧ 202001 ≤ h.IdPeriodo ≤ 203012
I4. no existen dos hechos con la misma clave compuesta
I5. no se emite ninguna etiqueta de la forma TOTAL, con "=",
    o perteneciente a RETENCIÓN, CERTIFICACIÓN, POBLACIONES VULNERABLES,
    EMPRENDIMIENTO o CONTRATOS DE APRENDIZAJE
```

### 5.2 Invariante de pureza de unidades

```text
I6. En FactMetas no coexisten conteos de personas y ratios porcentuales.
```

Por eso no se escribe la columna `Porcentaje`. El ratio se calcula en DAX:

```dax
%_Cumplimiento = DIVIDE([Ejecucion_Total], [Meta_Total], 0)
```

### 5.3 Invariante de conservación

```text
I7. suma_hojas = Σ hechos
    suma_hojas + Δ = total_reportado   (si total_reportado ≠ ∅)
```

### 5.4 Invariante de no invasión

```text
I8. la fuente se abre en modo de solo lectura;
    no se modifica, renombra ni deja un puntero abierto.
```

### 5.5 Invariante de escritura

```text
I9. el destino solo se reemplaza después de construir y verificar
    el libro completo en memoria.
```

---

## 6. Invariantes de ciclo

El recorrido de filas mantiene:

```text
L1. by_key contiene exactamente las filas atómicas aceptadas en el prefijo procesado.
L2. todas las claves de by_key son únicas.
L3. todo valor de by_key satisface Q1–Q3.
L4. la suma acumulada es la suma de los valores de by_key.
L5. el recorrido se detiene en la primera frontera:
    TOTAL FORMACION COMPLEMENTARIA
    o un encabezado de sección no atómica posterior a los hechos.
```

La frontera `L5` evita reimportar etiquetas repetidas en retención y certificación. Si una fuente depurada eliminó la fila de total, los encabezados `RETENCIÓN`, `CERTIFICACIÓN`, `POBLACIONES VULNERABLES`, etc. actúan como frontera de respaldo.

---

## 7. Función de mapeo dimensional

```text
M_dim: Etiqueta → (IdCategoria, IdNivelFormación)
```

`M_dim` es parcial y determinista. Una etiqueta fuera de `Dom(M_dim)` no se aproxima ni se imputa: se descarta.

### 7.1 Catálogo canónico

| Etiqueta | IdCategoria | IdNivel |
|---|---:|---:|
| Tecnólogos Regular - Presencial | 4 | 4 |
| Tecnólogos Regular - Virtual | 4 | 12 |
| Tecnólogos Regular - A Distancia | 4 | 13 |
| Tecnólogos CampeSENA | 10 | 4 |
| Tecnólogos Full Popular | 1 | 4 |
| Tecnólogos FIC | 3 | 4 |
| Operarios Regular | 4 | 2 |
| Operarios CampeSENA | 10 | 2 |
| Operarios Full Popular | 1 | 2 |
| Operarios FIC | 3 | 2 |
| Auxiliares Regular | 4 | 1 |
| Auxiliares CampeSENA | 10 | 1 |
| Auxiliares Full Popular | 1 | 1 |
| Técnico Regular - Presencial y a Distancia | 4 | 3 |
| Técnico Regular - Virtual | 4 | 14 |
| Técnico CampeSENA | 10 | 3 |
| Técnico Full Popular | 1 | 3 |
| Técnico Articulación con la Media | 16 | 3 |
| Técnico FIC | 3 | 3 |
| Programa de Bilingüismo - Virtual | 4 | 5 |
| Programa de Bilingüismo - Presencial | 4 | 6 |
| Formación Complementaria Regular - Virtual (Sin Bilingüismo) | 4 | 15 |
| Formación Complementaria Regular - Presencial (Sin Bilingüismo) | 4 | 16 |
| Placa huella 6 (incluida en FEC) | 3 | 17 |
| Otros programas FEC | 3 | 18 |
| Formación Complementaria CampeSENA | 10 | 19 |
| Formación Complementaria Full Popular | 1 | 20 |
| Formación Especial Popular (FEP) | 1 | 21 |

### 7.2 Categorías

| IdCategoria | Categoría |
|---:|---|
| 1 | Full Popular |
| 3 | FIC |
| 4 | Formación regular |
| 10 | CampeSENA |
| 16 | Articulación con la Media |

La numeración anterior proviene de la especificación formal. No coincide con la numeración secuencial de la hoja `DimCategoria` del libro de referencia; ver `MODELO_DIMENSIONAL.md`.

---

## 8. Algoritmo de normalización

```text
normalizar(F_raw):
  1. seleccionar hoja
  2. inferir periodo y fecha de corte
  3. para cada fila:
       si es frontera de sección → detener
       si no es fila atómica → continuar
       parsear Meta y Ejecución
       verificar no negatividad y unicidad
       agregar a by_key
  4. si by_key = ∅ → SourceNotRecognized
  5. ordenar por (IdCategoria, IdNivelFormación)
  6. verificar Q1–Q4
  7. leer total reportado (solo para conciliación)
  8. calcular Δ
  9. verificar Q5–Q7
 10. retornar (hechos, control)
```

### 8.1 Selección de hoja

```text
hoja = argmax_hoja (tiene_hechos, periodo, fecha_corte, nº_etiquetas_atómicas)
```

El orden lexicográfico garantiza que, ante dos cortes del mismo mes, se prefiera el de fecha más reciente. En abril se selecciona `30 ABRIL` sobre `20 ABRIL`.

### 8.2 Parseo de cantidades

```text
ParseInt(x):
  x ∈ {None, "", "-", "—", "–", "NaN", "null"} → 0
  x termina en "%" → ValueError
  x contiene letras, fechas o símbolos no numéricos → ValueError
  x = "1.523" → 1523
  x = "1.523.456" → 1523456
  x = "1.523,00" → 1523
  x = "1,5" → ValueError (fracción)
  x = "2026-05-31" → ValueError (fecha)
```

### 8.3 Fila atómica

```text
EsFilaAtomica(fila) =
  ∃ etiqueta no vacía L en fila:
      ¬EsSubtotal(L)
      ∧ Normalizar(L) ∈ Dom(M_dim)
      ∧ existen las dos celdas posicionales a la derecha de L
```

Se usan posiciones, no la lista de celdas no vacías. Así una ejecución vacía se conserva como `0` y no se corre el valor de Meta.

### 8.4 Subtotal

```text
EsSubtotal(L) =
  L contiene "="
  ∨ "total" ∈ palabras(Normalizar(L))
  ∨ Normalizar(L) comienza con un prefijo no atómico
```

Los marcadores de una letra entre paréntesis no bastan: `(M)` identifica Placa huella y `(S)` identifica FEP, ambos atómicos.

---

## 9. Idempotencia

### 9.1 Idempotencia lógica

```text
normalizar(F_raw) = (H, I)
normalizar(F_raw) = (H', I')
⇒ H = H' ∧ I = I'
```

El recorrido es determinista, el catálogo es una función, el orden de hechos es fijo y el diccionario de control no contiene timestamps.

### 9.2 Idempotencia de serialización

El XLSX se construye en memoria, se canoniza y se verifica:

1. se fijan las fechas de los miembros ZIP en `1980-01-01T00:00:00`;
2. se fijan los atributos externos;
3. se reemplaza `dcterms:created` y `dcterms:modified` por una fecha derivada del periodo;
4. se conserva el orden de miembros;
5. se usa el mismo nivel de compresión.

Por tanto:

```text
bytes(build(H, I)) = bytes(build(H, I))
```

y dos ejecuciones con las mismas fuentes producen archivos y manifiesto idénticos.

### 9.3 Reingesta

El descubrimiento excluye archivos cuyo nombre empieza por `Modelo_Normalizado_Metas_Centro_ASTIN` o `Consolidado_Metas`. Aunque el usuario apunte la salida como fuente, el ETL no la reprocesa.

---

## 10. Reconciliación

Sea:

```text
S = (Σ Meta atómica, Σ Ejecución atómica)
T = (Meta reportada, Ejecución reportada)
Δ = S − T
```

Estados:

| Estado | Condición |
|---|---|
| `CUADRA` | `Δ = (0, 0)` |
| `DIFERENCIA_FUENTE` | `Δ ≠ (0, 0)` |
| `SIN_TOTAL_REPORTADO` | `T = ∅` |

`Δ` se registra en `Control` y en el manifiesto. **No se ajusta** la tabla de hechos. La postcondición de conservación se cumple sobre las hojas atómicas; la diferencia es una propiedad del reporte fuente.

### 10.1 Serie 2026

| Periodo | Δ Meta | Δ Ejecución |
|---|---:|---:|
| 2026-04 | 0 | 0 |
| 2026-05 | 0 | 0 |
| 2026-08 | +90 | +98 |
| 2026-09 | +90 | +98 |
| 2026-10 | +90 | +57 |

---

## 11. Contrato del libro

### 11.1 Hojas

```text
SHEET_ORDER = (
  FactMetas,
  DimCentro,
  DimPeriodo,
  DimCategoria,
  DimNivelFormación,
  DimIndicador,
  Control
)
```

### 11.2 Postcondiciones de serialización

```text
W1. workbook.sheetnames = SHEET_ORDER
W2. encabezado(FactMetas) = FIELDS
W3. filas(FactMetas) = hechos ordenados
W4. no existe columna "Porcentaje"
W5. DimCentro contiene exactamente el centro procesado
W6. DimPeriodo contiene exactamente el periodo procesado
W7. DimCategoria contiene |CATEGORIES| + 1 filas
W8. DimNivelFormación contiene |LEVELS| + 1 filas
W9. DimIndicador contiene |INDICATORS| + 1 filas
W10. Control.IdPeriodo, Control.FilasHecho y Control.HashHecho coinciden
```

`verify_workbook_bytes` verifica `W1`–`W10` antes de que `atomic_bytes` reemplace el destino.

### 11.3 Escritura atómica

```text
1. construir libro en BytesIO
2. verificar W1–W10
3. escribir a un temporal en el mismo directorio
4. flush + fsync
5. os.replace(temporal, destino)
6. eliminar temporal si existe
```

Un lector nunca observa un archivo parcial.

---

## 12. Matriz de pruebas

| Propiedad | Prueba |
|---|---|
| Parseo español y rechazo de fracciones | `test_parse_int_*` |
| Rechazo de porcentajes y fechas | `test_parse_int_rejects_*` |
| Catálogo único de 28 pares | `test_catalog_*` |
| Purga de subtotales | `test_subtotal_labels_are_not_atomic` |
| Conservación atómica | `test_conservation_and_subtotal_purge_are_exact` |
| Multiesquema | `test_multischema_batch_keeps_one_schema` |
| Idempotencia lógica | pruebas con Hypothesis |
| Idempotencia de bytes | `test_synthetic_rerun_is_byte_identical` |
| Contrato del libro | `test_workbook_contains_exact_star_schema_and_control` |
| Verificación de serialización | `test_workbook_rejects_tampered_fact_sheet` |
| Duplicados idénticos | `test_identical_duplicate_period_is_registered_not_reprocessed` |
| Conflicto de periodo | `test_conflicting_period_fails_by_default` |
| Política `latest` | `test_latest_policy_selects_newest_cut` |
| `--strict` | `test_strict_fails_on_omitted_source` |
| `--fail-on-delta` | `test_fail_on_delta_blocks_output` |
| Regresión abril/agosto/septiembre/octubre | `test_desktop_sources.py` |
| Libro de mayo | `test_may_workbook_has_canonical_six_columns` |

---

## 13. Decisiones y límites documentados

1. **Libro de referencia:** se adopta su estructura de dimensiones + hechos, pero no su `FactMetas` con `IdIndicador` y `Porcentaje`. La tupla canónica solicitada usa `IdNivelFormación` y excluye porcentajes.
2. **Numeración de categorías:** se usa la de la especificación formal, no la secuencial del libro de referencia.
3. **Matriz ancha:** `METAS FORMACION 2026 - TAYANA.xlsx` se omite porque no tiene ejecución apilada. No se imputa ejecución cero.
4. **Fuente depurada:** un archivo sin total reportado puede ser normalizado, pero el estado será `SIN_TOTAL_REPORTADO`. Si además eliminó filas atómicas, el ETL no puede detectarlo; se recomienda usar los cortes completos.
5. **Tabla dispersa:** un indicador ausente no se convierte en cero. Ausencia y cero no son equivalentes.
6. **Porcentajes:** se calculan en DAX. No se almacenan.
