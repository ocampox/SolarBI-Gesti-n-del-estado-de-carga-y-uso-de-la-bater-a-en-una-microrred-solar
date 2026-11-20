-- Modelo dimensional SolarBI-Bateria (PostgreSQL 16). Idempotente.
CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS dw.dim_inversor (
  inverter_id smallint PRIMARY KEY, nombre text NOT NULL,
  capacidad_kwh numeric(6,2) NOT NULL DEFAULT 10.24,   -- 51.2 V x 200 Ah
  paneles smallint NOT NULL DEFAULT 26, potencia_inversor_kw numeric(4,1) NOT NULL DEFAULT 8.0);
INSERT INTO dw.dim_inversor VALUES (1,'Subsistema 1'),(2,'Subsistema 2') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS dw.dim_fecha (
  fecha date PRIMARY KEY,
  anio int GENERATED ALWAYS AS (EXTRACT(year FROM fecha)) STORED,
  mes int GENERATED ALWAYS AS (EXTRACT(month FROM fecha)) STORED,
  dia_semana int GENERATED ALWAYS AS (EXTRACT(isodow FROM fecha)) STORED);

-- Dimension construida por nosotros (no existe en la fuente): banda de estado de carga.
CREATE TABLE IF NOT EXISTS dw.dim_estado_soc (
  estado_key smallint PRIMARY KEY, estado text NOT NULL, soc_desde numeric NOT NULL, soc_hasta numeric NOT NULL);
INSERT INTO dw.dim_estado_soc VALUES (1,'Critico',0,20),(2,'Bajo',20,40),(3,'Medio',40,80),(4,'Alto',80,100.01)
  ON CONFLICT DO NOTHING;

-- Proceso 1. GRANO: una fila por inversor y hora UTC (Silver). Reemplaza lecturas de ~13 s.
CREATE TABLE IF NOT EXISTS dw.fact_bateria_hora (
  inverter_id smallint NOT NULL REFERENCES dw.dim_inversor,
  hora_utc timestamptz NOT NULL,
  n_lecturas int NOT NULL CHECK (n_lecturas > 0),
  -- Un intervalo de telemetría puede cruzar el límite de la hora; por ello el
  -- acumulado asignado a una hora puede superar levemente 3.600 segundos.
  seg_obs int NOT NULL CHECK (seg_obs >= 0),
  seg_hueco int NOT NULL DEFAULT 0, seg_soc_bajo int NOT NULL DEFAULT 0,
  soc_prom numeric(5,2) CHECK (soc_prom BETWEEN 0 AND 100), soc_min numeric(5,2), soc_max numeric(5,2),
  kwh_carga numeric(9,4) NOT NULL DEFAULT 0 CHECK (kwh_carga >= 0),
  kwh_descarga numeric(9,4) NOT NULL DEFAULT 0 CHECK (kwh_descarga >= 0),
  delta_soc_kwh numeric(9,4) NOT NULL DEFAULT 0,
  kwh_pv numeric(9,4) NOT NULL DEFAULT 0, kwh_carga_ac numeric(9,4) NOT NULL DEFAULT 0, kwh_red numeric(9,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (inverter_id, hora_utc));            -- PK sirve el UPSERT y los filtros por inversor+rango
CREATE INDEX IF NOT EXISTS ix_fbh_hora ON dw.fact_bateria_hora USING brin (hora_utc);  -- serie temporal ordenada, indice minimo

-- Proceso 2 (streaming). GRANO: una lectura por inversor y marca de tiempo; la escribe el simulador.
CREATE TABLE IF NOT EXISTS dw.fact_bateria_vivo (
  inverter_id smallint NOT NULL REFERENCES dw.dim_inversor, ts_utc timestamptz NOT NULL,
  soc numeric(5,2) NOT NULL CHECK (soc BETWEEN 0 AND 100), volt numeric(5,2), corriente_a numeric(6,2),
  PRIMARY KEY (inverter_id, ts_utc));

-- Proceso 3. GRANO: un registro de contexto por id original. Se minimiza en ETL:
-- no se almacena textual_description ni otro texto libre potencialmente personal.
CREATE TABLE IF NOT EXISTS dw.fact_contexto_minimo (
  contexto_id bigint PRIMARY KEY, recorded_utc timestamptz NOT NULL,
  inicio_utc timestamptz NOT NULL, fin_utc timestamptz NOT NULL,
  fuente varchar(80) NOT NULL, duracion_min numeric(12,2) NOT NULL CHECK (duracion_min >= 0),
  CHECK (fin_utc >= inicio_utc));
CREATE INDEX IF NOT EXISTS ix_contexto_intervalo ON dw.fact_contexto_minimo (inicio_utc, fin_utc);

CREATE TABLE IF NOT EXISTS dw.etl_audit (
  id serial PRIMARY KEY, ts timestamptz DEFAULT now(), fuente text, filas_leidas bigint, filas_validas bigint,
  horas_cargadas int, detalle jsonb);

-- Eventos: episodios de horas consecutivas con soc_min < 20 (gaps-and-islands).
CREATE OR REPLACE VIEW dw.vw_evento_soc_bajo AS
SELECT inverter_id, min(hora_utc) AS inicio_utc, max(hora_utc) + interval '1 hour' AS fin_utc,
       count(*)::int AS horas, min(soc_min) AS soc_min
FROM (SELECT *, hora_utc - (row_number() OVER (PARTITION BY inverter_id ORDER BY hora_utc)) * interval '1 hour' AS grp
      FROM dw.fact_bateria_hora WHERE soc_min < 20) t
GROUP BY inverter_id, grp;

CREATE OR REPLACE VIEW dw.vw_bateria_dia AS
SELECT inverter_id, (hora_utc AT TIME ZONE 'UTC')::date AS fecha,
  sum(kwh_carga) kwh_carga, sum(kwh_descarga) kwh_descarga, sum(kwh_pv) kwh_pv, sum(kwh_red) kwh_red,
  sum(soc_prom*seg_obs)/NULLIF(sum(seg_obs),0) AS soc_prom, min(soc_min) soc_min,
  100.0*sum(seg_soc_bajo)/NULLIF(sum(seg_obs),0) AS pct_tiempo_soc_bajo,
  100.0*sum(seg_obs)/(24*3600) AS pct_disponibilidad_registro
FROM dw.fact_bateria_hora GROUP BY 1,2;

-- KPI por inversor. Eficiencia = descarga / (carga - dSoC almacenado). Ciclos eq. = descarga / capacidad.
CREATE OR REPLACE VIEW dw.vw_kpi_inversor AS
SELECT f.inverter_id, round(sum(soc_prom*seg_obs)/sum(seg_obs),2) soc_prom, min(soc_min) soc_min, max(soc_max) soc_max,
  round(100.0*sum(seg_soc_bajo)/sum(seg_obs),2) pct_tiempo_soc_bajo,
  round(sum(kwh_carga),1) kwh_carga, round(sum(kwh_descarga),1) kwh_descarga,
  round(sum(kwh_descarga)/NULLIF(sum(kwh_carga)-sum(delta_soc_kwh),0),3) eficiencia_ida_vuelta,
  round(sum(kwh_descarga)/max(i.capacidad_kwh),1) ciclos_equivalentes,
  round(100.0*sum(seg_obs)/NULLIF(sum(seg_obs)+sum(seg_hueco),0),2) pct_datos_registrados,
  round(100.0*(1-sum(kwh_red)/NULLIF(sum(kwh_carga_ac),0)),1) autosuficiencia_pct
FROM dw.fact_bateria_hora f JOIN dw.dim_inversor i USING (inverter_id) GROUP BY f.inverter_id;

-- Rol de solo lectura para Grafana / Power BI (la clave llega por Secret, no por el repo).
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='bi_reader') THEN CREATE ROLE bi_reader NOLOGIN; END IF; END $$;
GRANT USAGE ON SCHEMA dw TO bi_reader; GRANT SELECT ON ALL TABLES IN SCHEMA dw TO bi_reader;
