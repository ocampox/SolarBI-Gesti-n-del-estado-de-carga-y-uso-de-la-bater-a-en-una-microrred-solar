# SolarBI — Estado de carga (SoC) y uso de la batería en una microrred solar

Parte del Taller 6 de Inteligencia de Negocios (Institución Universitaria Pascual Bravo, 2026-II): módulo de **gestión del estado de carga y uso de la batería** de la microrred híbrida OpenCEM. Flujo:

`SQLite OpenCEM (Bronze) → ETL Python (Silver horario + contexto minimizado) → PostgreSQL dimensional (esquema dw) → Grafana (operativo + alertas) / Power BI (analítico)`, todo contenerizado y desplegable en Kubernetes.

**Datos y cita (CC BY 4.0):** Bartels, T. S., Wu, R., Lu, X., Chen, Y., Lu, Y., Xia, F., Yang, H., Chen, Y., & Li, T. (2026). *OpenCEM: Multimodal photovoltaic and battery microgrid dataset with context records and sky imagery* (Version 1.0.0) [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.21436223 — Los datos crudos **no** están en este repositorio. Descarga de `opencem-dataset` (CSV) o del registro Zenodo y verifica el SHA-256 con `opencem-v1.0.0-SHA256SUMS.txt`.

## Estructura

```
etl/        etl_bateria.py (Bronze→Silver→PG), simulate.py (streaming), Dockerfile
sql/        01_schema.sql (DDL, vistas, rol de solo lectura), 02_consultas.sql (ventanas, comparativos)
grafana/    dashboards/bateria.json + provisioning (datasource, tablero, 2 alertas)
k8s/        manifiestos + kustomization.yaml (un comando)
powerbi/    SolarBI.pbip (PBIP + TMDL + PBIR, controlable por versiones)
tools/      gen_powerbi.py (regenera el proyecto Power BI)
tests/      test_etl.py (check mínimo del ETL)
docs/       kpi_resultados.csv, dq_resumen.json, DISENO.md (indicadores, modelo, calidad, seguridad)
```

## Resultados (calculados sobre la Bronze SQLite oficial: 2,99 M de lecturas)

| Inversor | SoC prom. | SoC mín. | % tiempo SoC<20 % | kWh cargados | kWh descargados | Ciclos eq. | Eficiencia ida y vuelta* | Datos registrados |
|---|---|---|---|---|---|---|---|---|
| 1 | 90,16 % | 6 % | 0,50 % | 467,2 | 488,8 | 47,7 | en calibración | 88,8 % |
| 2 | 82,24 % | 10 % | 2,33 % | 894,7 | 832,7 | 81,3 | en calibración | 75,9 % |

**Hallazgos:** el inversor 2 entrega más energía a la carga y pasa 2,33 % del tiempo observado por debajo de 20 % de SoC. Ambos inversores registran mínimos críticos (6 % y 10 %) y la disponibilidad queda por debajo de la meta de 95 %. La eficiencia se mantiene en calibración hasta validar capacidad real y convención de signos.

## Reproducir

**Local (Docker Compose):**
```bash
cp .env.example .env            # editar claves
# copiar opencem-v1.0.0.sqlite a ./data/
docker compose up -d postgres
docker compose --profile etl run --rm etl
docker compose up -d simulator grafana     # Grafana: http://localhost:3001
```
**Kubernetes (minikube/kind/Docker Desktop, un nodo):**
```bash
docker build -t solarbi-etl:1.0 etl && minikube image load solarbi-etl:1.0
minikube mount <ruta>/data:/data &                              # Bronze SQLite disponible para el Job
cp k8s/secret.env.example k8s/secret.env                        # editar claves (no se versiona)
kubectl kustomize k8s --load-restrictor LoadRestrictionsNone | kubectl apply -f -  # levanta todo
kubectl delete namespace solar-bi                               # elimina todo
```
Grafana: NodePort 30300 · PostgreSQL para Power BI/DBeaver: NodePort 30543 (o `kubectl -n solar-bi port-forward svc/postgres-ext 5433:5432`).
Power BI: abrir `powerbi/SolarBI.pbip`, apuntar la conexión a `localhost:5433`, base `solar_db`, y Actualizar.
Demo de resiliencia: `kubectl -n solar-bi delete pod postgres-0` (los datos siguen, hay PVC) y `kubectl -n solar-bi delete pod -l app=grafana` (vuelve con su tablero). Alerta: `kubectl -n solar-bi set env cronjob/simulador SIM_TRIGGER=1`.

## Estado de la verificación

Verificado: el ETL se ejecutó sobre la Bronze SQLite oficial: 2.989.759 lecturas de telemetría produjeron 14.076 filas horarias, y 25.178 contextos JSON fueron minimizados; `tests/test_etl.py` pasa. **No ejecutado en esta máquina** (Docker Desktop no estaba iniciado): PostgreSQL, Kubernetes, Grafana y Power BI. No se deben presentar como capturas reales hasta hacer el arranque y guardar la evidencia.

El JSON de contexto sí se integra mediante `etl/etl_contexto.py` con minimización previa: se excluye `textual_description` y se conservan únicamente fuente e intervalo. Consulte `docs/DICCIONARIO_Y_LINAJE.md`.
