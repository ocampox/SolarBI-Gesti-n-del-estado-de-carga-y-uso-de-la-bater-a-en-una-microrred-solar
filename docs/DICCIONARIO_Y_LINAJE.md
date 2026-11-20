# Diccionario de datos y linaje de SolarBI

## Capas y trazabilidad

| Capa | Activo | Regla de gobierno | Salida y uso |
|---|---|---|---|
| Bronze | `opencem-v1.0.0.sqlite` | Solo lectura, verificado con SHA-256; no se versiona | Tablas `analog_measurements` y `context` |
| Silver | `fact_bateria_hora.csv` | Limpieza física, integración entre lecturas contiguas y agregación hora UTC | Auditoría y carga analítica |
| Gold | Esquema `dw` PostgreSQL | Llaves, restricciones e índices; UPSERT idempotente | Power BI, Grafana y consultas SQL |

## Tablas Gold

| Tabla | Grano y llaves | Campos principales y tipo | Origen y transformación |
|---|---|---|---|
| `dim_inversor` | Un inversor; PK `inverter_id` | `nombre text`, `capacidad_kwh numeric`, `paneles smallint` | Parámetros técnicos documentados del subsistema; dimensión conformada. |
| `dim_fecha` | Un día; PK `fecha` | `anio int`, `mes int`, `dia_semana int` | Derivada de `hora_utc`; soporta jerarquía año-mes-día. |
| `dim_estado_soc` | Una banda; PK `estado_key` | `estado text`, `soc_desde numeric`, `soc_hasta numeric` | Creada por el equipo: Crítico 0-20, Bajo 20-40, Medio 40-80, Alto 80-100. |
| `fact_bateria_hora` | Inversor-hora UTC; PK `(inverter_id,hora_utc)`, FK a inversor | `soc_prom`, `soc_min`, `kwh_pv`, `kwh_carga_ac`, `kwh_red`, `kwh_carga`, `kwh_descarga` como `numeric`; tiempos como `int` | `analog_measurements`; se excluyen SoC nulo, SoC fuera de 0-100 y voltaje fuera de 10-80 V; se evita integrar huecos >600 s. |
| `fact_bateria_vivo` | Inversor-marca de tiempo; PK `(inverter_id,ts_utc)` | `soc`, `volt`, `corriente_a` | Simulador para operación; no sustituye el histórico Silver. |
| `fact_contexto_minimo` | Contexto original; PK `contexto_id` | `recorded_utc`, `inicio_utc`, `fin_utc`, `fuente`, `duracion_min` | JSON `context.value`; se elimina `textual_description` antes de llegar a Gold. |
| `etl_audit` | Ejecución | conteos y `detalle jsonb` | ETL; demuestra reglas, conciliación y atributo protegido. |

## Unidades físicas y evidencia

| Campo Bronze | Unidad | Evidencia | Uso Gold |
|---|---|---|---|
| `read_ts` | segundos Unix UTC | `column_dictionary.csv` de OpenCEM | `hora_utc`, intervalos y disponibilidad. |
| `battsoc` | porcentaje | Diccionario OpenCEM | estado, promedio y mínimo de SoC. |
| `battvolt` | voltios | Diccionario OpenCEM | control de rango y cálculo de descarga. |
| `battcurr` | amperios | Diccionario OpenCEM | descarga cuando supera la banda muerta de 1 A. |
| `battchgpower`, `pv1power`, `outsumw`, `gridpowerw_a` | vatios | Diccionario OpenCEM | se integran por intervalo a kWh. |

El índice BRIN de `hora_utc` favorece series temporales grandes con bajo espacio; la clave compuesta favorece el UPSERT y filtros por inversor y rango. La constelación evita duplicar dimensiones y se prefiere a copo de nieve porque las tres dimensiones son pequeñas y el consumo analítico privilegia consultas simples.
