-- Consultas de negocio (ventanas y comparativos). Ejecutar en DBeaver.
-- Q1 SoC promedio mensual y variacion vs mes anterior (LAG)
SELECT inverter_id, date_trunc('month',fecha)::date mes, round(avg(soc_prom),1) soc_prom,
       round(avg(soc_prom) - lag(avg(soc_prom)) OVER (PARTITION BY inverter_id ORDER BY date_trunc('month',fecha)),1) var_vs_mes_ant
FROM dw.vw_bateria_dia GROUP BY inverter_id, date_trunc('month',fecha) ORDER BY 1,2;
-- Q2 Ranking de dias con mas ciclos de descarga por inversor (RANK)
SELECT * FROM (SELECT inverter_id, fecha, round(kwh_descarga,2) kwh_descarga,
       rank() OVER (PARTITION BY inverter_id ORDER BY kwh_descarga DESC) r FROM dw.vw_bateria_dia) t WHERE r<=5;
-- Q3 Perfil horario: a que hora se descarga la bateria (franja)
SELECT inverter_id, extract(hour FROM hora_utc AT TIME ZONE 'Asia/Shanghai') hora_local,
       round(avg(kwh_descarga)::numeric,3) kwh_descarga_prom, round(avg(soc_prom),1) soc_prom
FROM dw.fact_bateria_hora GROUP BY 1,2 ORDER BY 1,2;
-- Q4 Acumulado de energia descargada (SUM OVER)
SELECT inverter_id, fecha, sum(kwh_descarga) OVER (PARTITION BY inverter_id ORDER BY fecha) kwh_desc_acum FROM dw.vw_bateria_dia;
-- Q5 Episodios de SoC critico
SELECT * FROM dw.vw_evento_soc_bajo ORDER BY horas DESC LIMIT 20;
-- Q6 Costo evitado en COP: descarga cubierta por bateria x tarifa (ajustar tarifa y justificar)
SELECT inverter_id, round(sum(kwh_descarga)*850) AS cop_energia_desde_bateria FROM dw.fact_bateria_hora GROUP BY 1;
-- Q7 Contexto minimizado: consulta sobre JSON nativo (audit) y eventos sin texto libre.
SELECT fuente, count(*) AS eventos, round(sum(duracion_min)/60.0,1) AS horas_contexto
FROM dw.fact_contexto_minimo GROUP BY fuente ORDER BY eventos DESC;
SELECT ts, detalle->>'atributo_excluido' AS atributo_protegido
FROM dw.etl_audit WHERE detalle ? 'atributo_excluido' ORDER BY ts DESC;
