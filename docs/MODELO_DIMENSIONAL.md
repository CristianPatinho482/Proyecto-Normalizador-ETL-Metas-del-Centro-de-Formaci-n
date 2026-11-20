# Modelo dimensional para Power BI

## 1. Esquema en estrella

```text
                         ┌─────────────────┐
                         │    DimCentro    │
                         │  IdCentro (PK)  │
                         └────────┬────────┘
                                  │ 1
                                  │
                                  │ N
┌─────────────────┐      ┌────────▼────────┐      ┌──────────────────────┐
│   DimPeriodo    │ 1  N │    FactMetas    │ N  1 │ DimNivelFormación    │
│ IdPeriodo (PK)  ├──────┤ IdCentro        ├──────┤ IdNivelFormación (PK)│
└─────────────────┘      │ IdPeriodo       │      └──────────────────────┘
                         │ IdCategoria     │
                         │ IdNivelFormación│      ┌──────────────────────┐
                         │ Meta            │ N  1 │     DimCategoria     │
                         │ Ejecución       ├──────┤ IdCategoria (PK)     │
                         └─────────────────┘      └──────────────────────┘

                         ┌─────────────────────────────┐
                         │        DimIndicador         │
                         │ (IdCategoria, IdNivel) (PK) │
                         │ Indicador                   │
                         └─────────────────────────────┘
```

`DimIndicador` es una dimensión de catálogo con clave compuesta `(IdCategoria, IdNivelFormación)`. No es necesaria para el filtrado básico, pero permite mostrar el nombre legible del indicador sin duplicar etiquetas en los hechos.

## 2. Tablas

### 2.1 `FactMetas`

| Columna | Tipo | Descripción |
|---|---|---|
| `IdCentro` | Entero | `1` para ASTIN |
| `IdPeriodo` | Entero | `YYYYMM` |
| `IdCategoria` | Entero | FK a `DimCategoria` |
| `IdNivelFormación` | Entero | FK a `DimNivelFormación` |
| `Meta` | Entero | Meta del periodo |
| `Ejecución` | Entero | Ejecución del periodo |

Clave primaria compuesta:

```text
(IdCentro, IdPeriodo, IdCategoria, IdNivelFormación)
```

No contiene `Porcentaje`, subtotales, retención ni certificación. Es una tabla dispersa: solo aparecen los indicadores reportados en el corte.

### 2.2 `DimCentro`

| Columna | Valor |
|---|---|
| `IdCentro` | `1` |
| `CodigoCentro` | `9230` |
| `NombreCentro` | `CENTRO NACIONAL DE ASISTENCIA TECNICA A LA INDUSTRIA - ASTIN` |
| `Regional` | `VALLE` |

### 2.3 `DimPeriodo`

| Columna | Ejemplo |
|---|---|
| `IdPeriodo` | `202605` |
| `Anio` | `2026` |
| `Mes` | `5` |
| `NombreMes` | `Mayo` |
| `FechaCorte` | `2026-05-31` |

### 2.4 `DimCategoria`

| IdCategoria | Categoría |
|---:|---|
| 1 | Full Popular |
| 3 | FIC |
| 4 | Formación regular |
| 10 | CampeSENA |
| 16 | Articulación con la Media |

### 2.5 `DimNivelFormación`

| IdNivelFormación | NivelFormación |
|---:|---|
| 1 | Auxiliar |
| 2 | Operario |
| 3 | Técnico |
| 4 | Tecnólogo |
| 5 | Bilingüismo - Virtual |
| 6 | Bilingüismo - Presencial |
| 12 | Tecnólogo - Virtual |
| 13 | Tecnólogo - A Distancia |
| 14 | Técnico - Virtual |
| 15 | Formación Complementaria Regular - Virtual (Sin Bilingüismo) |
| 16 | Formación Complementaria Regular - Presencial (Sin Bilingüismo) |
| 17 | Placa Huella 6 (FEC) |
| 18 | Otros Programas FEC |
| 19 | Formación Complementaria CampeSENA |
| 20 | Formación Complementaria Full Popular |
| 21 | Formación Especial Popular (FEP) |

### 2.6 `DimIndicador`

| Columna | Descripción |
|---|---|
| `IdCategoria` | Parte de la clave compuesta |
| `IdNivelFormación` | Parte de la clave compuesta |
| `Indicador` | Etiqueta canónica legible |

Contiene los 28 indicadores atómicos, incluso si un periodo no los reporta. Esto conserva el catálogo entre periodos.

### 2.7 `Control`

Tabla clave-valor con:

- `Esquema`, `VersionETL`;
- `IdCentro`, `IdPeriodo`, `Periodo`, `Anio`, `Mes`, `NombreMes`, `FechaCorte`;
- `Fuente`, `Hoja`, `ReglaPeriodo`, `Sha256Fuente`, `Layout`;
- `FilasHecho`, `IndicadoresReconocidos`;
- `SumaMeta`, `SumaEjecucion`;
- `TotalReportadoMeta`, `TotalReportadoEjecucion`;
- `DeltaMeta`, `DeltaEjecucion`, `EstadoConciliacion`;
- `Advertencias`;
- `HashHecho`.

## 3. Relaciones en Power BI

Crear relaciones uno-a-muchos, con filtro simple desde la dimensión hacia los hechos:

```text
DimCentro[IdCentro]             1 ── * FactMetas[IdCentro]
DimPeriodo[IdPeriodo]           1 ── * FactMetas[IdPeriodo]
DimCategoria[IdCategoria]       1 ── * FactMetas[IdCategoria]
DimNivelFormación[IdNivelFormación] 1 ── * FactMetas[IdNivelFormación]
```

`DimIndicador` no necesita relación física si se usa como tabla de consulta; si se relaciona, debe hacerse por la clave compuesta o por una columna calculada concatenada. La opción recomendada es no relacionarla y usarla como catálogo de referencia.

## 4. Medidas DAX

```dax
Meta_Total = SUM ( FactMetas[Meta] )

Ejecucion_Total = SUM ( FactMetas[Ejecución] )

%_Cumplimiento =
DIVIDE ( [Ejecucion_Total], [Meta_Total], 0 )

Brecha =
[Ejecucion_Total] - [Meta_Total]

Meta_Periodo_Anterior =
CALCULATE (
    [Meta_Total],
    FILTER (
        ALL ( DimPeriodo ),
        DimPeriodo[IdPeriodo]
            = MAX ( DimPeriodo[IdPeriodo] ) - 100
    )
)
```

No crear una medida `SUM(FactMetas[Porcentaje])`: esa columna no existe por diseño.

## 5. Consulta Power Query para los libros mensuales

Si se usa la carpeta de libros `.xlsx`, una consulta de combinación puede ser:

```m
let
    Origen = Folder.Files(
        "C:\Users\capatino\OneDrive - Servicio Nacional de Aprendizaje\BACKUP DISCO\Mis proyectos\AREA LABORAL\SENA\POWER BI\Sistema de control e información - Estado de las metas centro ASTIN\01_Metas_Normalizadas"
    ),
    SoloXlsx = Table.SelectRows(
        Origen,
        each [Extension] = ".xlsx"
            and not Text.StartsWith([Name], "~$")
    ),
    ConHechos = Table.AddColumn(
        SoloXlsx,
        "FactMetas",
        each Excel.Workbook([Content], null, true){[Item = "FactMetas", Kind = "Sheet"]}[Data]
    ),
    Expandir = Table.ExpandTableColumn(
        ConHechos,
        "FactMetas",
        {"IdCentro", "IdPeriodo", "IdCategoria", "IdNivelFormación", "Meta", "Ejecución"}
    ),
    Tipos = Table.TransformColumnTypes(
        Expandir,
        {
            {"IdCentro", Int64.Type},
            {"IdPeriodo", Int64.Type},
            {"IdCategoria", Int64.Type},
            {"IdNivelFormación", Int64.Type},
            {"Meta", Int64.Type},
            {"Ejecución", Int64.Type}
        }
    )
in
    Tipos
```

Para el CSV canónico:

```m
let
    Origen = Folder.Files("...\01_Metas_Normalizadas"),
    SoloCsv = Table.SelectRows(
        Origen,
        each [Extension] = ".csv" and not Text.StartsWith([Name], "~$")
    ),
    Datos = Table.AddColumn(
        SoloCsv,
        "Datos",
        each Csv.Document([Content], [Delimiter = ";", Encoding = 65001])
    ),
    Expandir = Table.ExpandTableColumn(
        Datos,
        "Datos",
        {"Column1", "Column2", "Column3", "Column4", "Column5", "Column6"},
        {"IdCentro", "IdPeriodo", "IdCategoria", "IdNivelFormación", "Meta", "Ejecución"}
    ),
    SinCabeceras = Table.SelectRows(Expandir, each [IdCentro] <> "IdCentro"),
    Tipos = Table.TransformColumnTypes(
        SinCabeceras,
        {
            {"IdCentro", Int64.Type},
            {"IdPeriodo", Int64.Type},
            {"IdCategoria", Int64.Type},
            {"IdNivelFormación", Int64.Type},
            {"Meta", Int64.Type},
            {"Ejecución", Int64.Type}
        }
    )
in
    Tipos
```

## 6. Diferencia con el libro de referencia

El libro `Modelo_Normalizado_Metas_Centro_ASTIN_Mayo2026.xlsx` es una referencia de **estructura** (dimensiones + hechos + control), no de identificadores. Tiene dos diferencias deliberadas:

1. Usa `IdIndicador` y una columna `Porcentaje` en `FactMetas`. La tupla canónica solicitada usa `IdNivelFormación` y no admite porcentajes.
2. Su `DimCategoria` numera secuencialmente (`1 = CampeSENA`, `2 = FIC`, `3 = Full Popular`, `4 = Formación regular`, `10 = Articulación`). La especificación formal usa `1 = Full Popular`, `3 = FIC`, `4 = Formación regular`, `10 = CampeSENA`, `16 = Articulación`.

Este proyecto usa la numeración de la especificación formal. Si se migra un tablero existente que dependía de la numeración del libro de referencia, debe actualizarse el mapeo de categorías en Power BI.

## 7. Tabla dispersa y ausencia

La tabla de hechos no rellena con cero los indicadores ausentes. La razón es semántica:

```text
ausencia ≠ cero
```

Un indicador que no aparece en el corte puede significar que no se reportó, que no aplica o que la fuente lo omitió. Convertirlo en cero distorsionaría los promedios y los porcentajes. Para conservar la comparabilidad entre periodos, `DimIndicador` incluye los 28 indicadores aunque un periodo solo reporte 20.

## 8. Conciliación visible

La hoja `Control` y el manifiesto registran:

```text
SumaMeta, SumaEjecucion
TotalReportadoMeta, TotalReportadoEjecucion
DeltaMeta, DeltaEjecucion
EstadoConciliacion ∈ {CUADRA, DIFERENCIA_FUENTE, SIN_TOTAL_REPORTADO}
```

En 2026, agosto, septiembre y octubre tienen diferencias de fuente (`+90` en Meta y `+98`, `+98`, `+57` en Ejecución). No se corrigen en el ETL. Si un tablero necesita cuadrar con el total de cabecera, debe mostrar la diferencia como nota de calidad, no alterar los hechos atómicos.
