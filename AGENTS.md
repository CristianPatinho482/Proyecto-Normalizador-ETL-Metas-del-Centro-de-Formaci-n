# Guía de contribución

- Mantén lectura, catálogo, reglas, normalización, libro y persistencia en módulos separados.
- La tabla `FactMetas` tiene exactamente seis columnas: `IdCentro`, `IdPeriodo`, `IdCategoria`, `IdNivelFormación`, `Meta`, `Ejecución`.
- No emitas subtotales, porcentajes, retención, certificación ni poblaciones vulnerables como hechos atómicos.
- No agregues `Porcentaje` ni columnas calculadas a `FactMetas`; los ratios se calculan en DAX.
- No cambies los pares `(IdCategoria, IdNivelFormación)` del catálogo sin actualizar la especificación formal, el modelo dimensional y las pruebas.
- La hoja `DimCategoria` debe usar la numeración de la especificación formal (`1`, `3`, `4`, `10`, `16`), no la numeración secuencial del libro de referencia.
- La carpeta de salida contiene libros mensuales y, si se solicita, CSV canónicos. Manifiestos y errores van a `control_metas`.
- Las escrituras son atómicas, deterministas e idempotentes. El XLSX se verifica antes de reemplazar el destino.
- No escribas marcas de tiempo de ejecución en los hechos, el libro ni el manifiesto.
- Usa fuentes sintéticas en pruebas. No copies archivos operativos ni rutas privadas a fixtures o Git.
- Las fuentes reales se leen en modo de solo lectura. No sobrescribas ni edites archivos de `Metas/` o de `Desktop\Metas de formación`.
- Si el esquema, una interpretación del reporte o una política de duplicados cambia, actualiza contrato, pruebas y documentación.
