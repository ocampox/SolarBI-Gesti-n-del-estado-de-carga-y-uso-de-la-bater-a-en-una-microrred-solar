# Diseño: SoC y uso de la batería

> Nota de actualización: este documento conserva el diseño inicial basado en CSV. La implementación y cifras vigentes usan la Bronze SQLite oficial, incorporan `etl_contexto.py` y se documentan en `DICCIONARIO_Y_LINAJE.md` y el informe final.

## 1. Usuarios y preguntas
| Usuario | Pregunta |
|---|---|
| Dirección de infraestructura | ¿Cuánta batería necesito? ¿Qué subsistema la usa más? ¿Cuánto ahorro en COP? |
| Mantenimiento | ¿Algún banco está en SoC crítico ahora? ¿Dejaron de llegar lecturas? |

## 2. Diagnóstico de la fuente (4.021.653 filas, 2 inversores, 2025-07-12 a 2026-04-12, ~13 s)
- `battcurr` es **uint16/10**: valores > 3276,7 son negativos (ej. 6553,5 = −0,1 A). Evidencia: 49.286 (inv 1) y 82.071 (inv 2) filas; sin decodificar la carga resultaba ~58 MWh (absurdo).
- Convención de signo **verificada** con SoC: corriente > 3 A ⇒ el SoC cae ~2 puntos en 30 min ⇒ **positivo = descarga, negativo = carga**. `battchgpower` (≥ 0 siempre) = potencia de carga y coincide con V·|I| (p. ej. 8,2 A × 53,5 V ≈ 438 W).
- Corriente de reposo de ~0,5 A con la batería en flotación (≈ 26 W × 10.800 h ≈ 290 kWh espurios) → banda muerta de 1 A.
- Huecos de registro: ~1.165 h por inversor (≈ 10 % del tiempo); no se imputan.
- Unidades: SoC %, voltaje V, corriente A, potencias W; capacidad nominal 51,2 V × 200 Ah = 10,24 kWh por banco (README OpenCEM; supuesto a calibrar).

## 3. Reglas de limpieza (conteos en `docs/dq_resumen.json`)
| Regla | Inv 1 | Inv 2 |
|---|---|---|
| Leídas | 2.216.932 | 1.804.703 |
| R1 SoC nulo → descarta | 1.300 | 1.978 |
| R2 SoC fuera de [0,100] o V fuera de [10,80] → descarta | 1.249 | 2.234 |
| Válidas | 2.214.383 | 1.800.491 |
| R3 corriente decodificada (uint16) | 49.286 | 82.071 |
| R4 huecos > 600 s (no se integran) / orden-duplicado | 301 / 18 | 196 / 15 |
| R5 \|I\| ≤ 1 A no cuenta como descarga | regla de energía | regla de energía |

Inválido vs. evento real: un SoC bajo (p. ej. 10 %) es un **evento operativo real**, no se descarta; solo se descartan valores físicamente imposibles. **Silver horario:** se gana volumen (4 M → ~11 k filas), consultas rápidas y PK simple; se pierde la dinámica de segundos (picos de corriente, rampas) — para eso existe `fact_bateria_vivo`.

## 4. Catálogo de indicadores
| Indicador | Fórmula | Unidad | Granularidad | Meta/umbral | Fuente | Usuario |
|---|---|---|---|---|---|---|
| SoC promedio | Σ(soc_prom·seg_obs)/Σseg_obs | % | inversor-hora/día/mes | > 40 % | battsoc | Dirección |
| SoC mínimo | MIN(soc_min) | % | inversor-día | ≥ 20 % | battsoc | Mantenimiento |
| % tiempo SoC bajo | seg(SoC<20)/seg_obs | % | inversor-mes | < 1 % | battsoc | Dirección |
| Energía cargada / descargada | ∫battchgpower dt ; ∫V·I⁺ dt | kWh | inversor-hora | — | battchgpower, battvolt, battcurr | Dirección |
| Ciclos equivalentes (propio) | kWh descargados / capacidad | ciclos | inversor-mes | informativo (vida útil de litio ~3.000–6.000) | derivado | Dirección |
| Eficiencia ida y vuelta (propio) | descarga / (carga − ΔSoC·cap) | ratio | inversor | 0,85–0,95 | derivado | Dirección |
| Autosuficiencia | 1 − kWh red / kWh carga AC | % | inversor-mes | informativo | gridpowerw_a, outsumw | Dirección |
| Disponibilidad del registro | seg_obs/(seg_obs+seg_hueco) | % | inversor-día | > 95 % | read_ts | Mantenimiento |
| % datos válidos | válidas/leídas | % | inversor | > 99 % | ETL | Ambos |
| Ahorro COP | kWh descargados × tarifa | COP | inversor-mes | tarifa **850 COP/kWh** (supuesto; el equipo debe elegirla y citar fuente) | derivado | Dirección |

**Indicador clásico no calculable:** Performance Ratio (PR) / factor de capacidad: requiere irradiancia en plano de paneles (o potencia nominal vs. irradiación) que la fuente tabular no trae (las imágenes de cielo quedan fuera del alcance). Acción: usar potencia relativa a la nominal (26 × 480 W) como proxy y proponer un piranómetro.

## 5. Modelo dimensional (constelación)
- **Hechos:** `fact_bateria_hora` (grano inversor-hora, Silver) y `fact_bateria_vivo` (grano inversor-lectura, streaming). Eventos de SoC crítico se modelan como vista de episodios (`vw_evento_soc_bajo`, gaps-and-islands), separados de las lecturas, porque son eventos con inicio/fin y no mediciones.
- **Dimensiones:** `dim_inversor`, `dim_fecha`, `dim_estado_soc` (**construida por nosotros**: Crítico/Bajo/Medio/Alto).
- **Bus matrix**

| Proceso | dim_inversor | dim_fecha | dim_estado_soc |
|---|---|---|---|
| Batería por hora | ✔ | ✔ | (por banda de soc_min) |
| Lectura en vivo | ✔ | ✔ (ts) | ✔ |
- **SCD (bonificación):** `dim_inversor` Tipo 2 si cambia la capacidad instalada (valid_from/valid_to); hoy es estática, se documenta sin implementar.
- Índices: PK compuesta (inversor, hora) sirve UPSERT y filtros por rango; BRIN sobre hora (tabla append-only ordenada por tiempo, índice minúsculo).

## 6. Calidad y conciliación
Conciliación: Σ(`validas`) en `dw.etl_audit` = filas válidas de la fuente; la carga es idempotente (UPSERT por PK; ejecutarla dos veces no cambia totales).
**Limitación abierta:** la eficiencia del inversor 1 (1,155) es > 1, imposible físicamente. Causas probables: carga no observada durante huecos y offset de corriente < 1 A. Falta calibrar capacidad real y banda muerta; no usar esa cifra como resultado.

## 7. Seguridad y ética
Credenciales solo en `Secret` (generado desde `k8s/secret.env`, no versionado) y `.env`; rol `bi_reader` de solo lectura para Grafana/Power BI; PostgreSQL publicado solo en loopback (compose). La tabla de contexto (JSON con descripciones de tareas del personal) no se carga en este módulo; si se carga, aplicar minimización de la Ley 1581 de 2012 (excluir texto libre con datos personales).

## 8. Power BI vs Grafana
Power BI: decisión de inversión, histórico, escenarios (tarifa/capacidad), actualización diaria/manual. Grafana: operación, estado actual y alertas, refresco 10 s sobre `fact_bateria_vivo`. No se intercambian: Grafana no modela dimensiones ni what-if; Power BI no alerta en casi tiempo real.

## 9. Evolución
Reemplazar CSV por lectura Modbus/RS485 o SCADA → gateway que publique a MQTT/Kafka → consumidor que escribe `fact_bateria_vivo`; el Silver horario se regenera con un job por hora.
