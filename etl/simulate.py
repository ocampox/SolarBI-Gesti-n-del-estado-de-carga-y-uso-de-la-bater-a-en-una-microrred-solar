"""Simulador: una lectura de bateria por inversor cada SIM_INTERVAL_SEC (CronJob/Deployment). Idempotente por (inverter_id, ts_utc).
SIM_TRIGGER=1 fuerza el inversor 2 a descender hasta SoC critico para disparar la alerta de Grafana."""
import math, os, random, time
from datetime import datetime, timezone
import psycopg

DSN = (f"host={os.environ['POSTGRES_HOST']} port={os.getenv('POSTGRES_PORT','5432')} dbname={os.environ['POSTGRES_DB']} "
       f"user={os.environ['POSTGRES_USER']} password={os.environ['POSTGRES_PASSWORD']}")
EVERY = int(os.getenv("SIM_INTERVAL_SEC", "5")); TRIGGER = os.getenv("SIM_TRIGGER", "0") == "1"
N = int(os.getenv("SIM_TICKS", "0"))  # 0 = infinito

def main():
    with psycopg.connect(DSN, autocommit=True) as c:
        cur = c.cursor()
        cur.execute("SELECT inverter_id, soc FROM dw.fact_bateria_vivo WHERE (inverter_id, ts_utc) IN "
                    "(SELECT inverter_id, max(ts_utc) FROM dw.fact_bateria_vivo GROUP BY 1)")
        soc = {1: 90.0, 2: 45.0} | {i: float(s) for i, s in cur.fetchall()}   # continua donde quedo
        k = 0
        while N == 0 or k < N:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            sol = max(0.0, math.sin((now.hour - 6) * math.pi / 12))
            for inv in (1, 2):
                i_a = (1.0 - 6 * sol) * (1 if inv == 1 else 1.4) + random.uniform(-.3, .3)   # >0 descarga, <0 carga (convencion OpenCEM)
                if TRIGGER and inv == 2: i_a = 12.0
                soc[inv] = min(100.0, max(5.0, soc[inv] - i_a * 0.02))
                cur.execute("INSERT INTO dw.fact_bateria_vivo VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (inv, now, round(soc[inv], 2), round(48 + soc[inv] * .064, 2), round(i_a, 2)))
            print(now, {k_: round(v, 1) for k_, v in soc.items()}, flush=True)
            k += 1; time.sleep(EVERY)

if __name__ == "__main__": main()
