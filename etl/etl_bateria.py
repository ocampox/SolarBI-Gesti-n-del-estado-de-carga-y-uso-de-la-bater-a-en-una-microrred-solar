"""ETL Bronze (CSV OpenCEM) -> Silver horario (fact_bateria_hora) -> PostgreSQL.

Reglas (conteos en dq_resumen.json y en dw.etl_audit):
  R1 SoC nulo/no numerico -> descarta   R2 SoC fuera [0,100] o V fuera [V_MIN,V_MAX] -> descarta
  R3 battcurr es uint16/10: >3276.7 => negativo (A).  Convencion verificada: >0 = DESCARGA, <0 = CARGA
  R5 |I| <= BANDA_MUERTA_A (offset de reposo ~0.5 A, ~290 kWh espurios) no cuenta como descarga
  R4 hueco entre lecturas > GAP_MAX_S: no se integra energia (se cuenta en seg_hueco, no se inventa dato)
Carga = integral de battchgpower (W, siempre >=0); descarga = integral de V*I con I>0.
Idempotente: PK (inverter_id, hora_utc) + ON CONFLICT DO UPDATE.
Uso: python etl_bateria.py <bronze.sqlite|data/measurements> [salida_dir]   (POSTGRES_HOST definido => tambien carga a PG)
"""
import csv, glob, io, json, os, sys, sqlite3
from collections import defaultdict

GAP_MAX_S = int(os.getenv("GAP_MAX_S", "600"))   # umbral configurable (ConfigMap)
V_MIN, V_MAX = 10, 80
BANDA_MUERTA_A = float(os.getenv("BANDA_MUERTA_A", "1.0"))  # corriente de reposo ~0.5 A del sensor: no es descarga real
SOC_BAJO = float(os.getenv("SOC_BAJO", "20"))
CAP_KWH = float(os.getenv("CAP_KWH", "10.24"))   # 51.2 V x 200 Ah (README OpenCEM); calibrar si difiere
COLS = ["inverter_id", "hora_utc", "n_lecturas", "seg_obs", "seg_hueco", "seg_soc_bajo", "soc_prom", "soc_min",
        "soc_max", "kwh_carga", "kwh_descarga", "delta_soc_kwh", "kwh_pv", "kwh_carga_ac", "kwh_red"]

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def _filas_bronze(origen):
    """Lee la Bronze inmutable: carpeta CSV heredada o SQLite oficial de OpenCEM."""
    if os.path.isfile(origen) and origen.lower().endswith((".sqlite", ".db")):
        con = sqlite3.connect(f"file:{os.path.abspath(origen)}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            for r in con.execute("SELECT read_ts,inverter,battvolt,battcurr,battsoc,battchgpower,pv1power,outsumw,gridpowerw_a FROM analog_measurements ORDER BY inverter,read_ts"):
                yield dict(r)
        finally:
            con.close()
        return
    for fn in sorted(glob.glob(os.path.join(origen, "*.csv"))):
        with open(fn, newline="", encoding="utf-8") as fh:
            yield from csv.DictReader(fh)

def extraer(origen):
    H = defaultdict(lambda: defaultdict(float))
    dq = defaultdict(lambda: defaultdict(int))
    ult = {}
    for r in _filas_bronze(origen):
        inv = int(r["inverter"]); d = dq[inv]; d["leidas"] += 1
        ts, soc, v, i = num(r["read_ts"]), num(r["battsoc"]), num(r["battvolt"]), num(r["battcurr"])
        if ts is None or soc is None: d["R1_soc_nulo"] += 1; continue
        if not 0 <= soc <= 100 or v is None or not V_MIN <= v <= V_MAX:
            d["R2_fuera_rango"] += 1; continue
        if i is not None and i > 3276.7: i -= 6553.6; d["R3_corriente_decodificada"] += 1
        d["validas"] += 1
        h = H[(inv, int(ts // 3600) * 3600)]
        h["n"] += 1; h["soc_sum"] += soc
        h["soc_min"] = soc if "soc_min" not in h else min(h["soc_min"], soc)
        h["soc_max"] = max(h["soc_max"], soc)
        p = ult.get(inv)
        ult[inv] = (ts, soc, v, i, num(r["battchgpower"]), num(r["pv1power"]), num(r["outsumw"]), num(r["gridpowerw_a"]))
        if not p: continue
        dt = ts - p[0]
        if dt <= 0: d["R4_orden_o_duplicado"] += 1; continue
        if dt > GAP_MAX_S: h["seg_hueco"] += dt; d["R4_huecos"] += 1; continue
        h["seg_obs"] += dt
        if p[1] < SOC_BAJO: h["seg_soc_bajo"] += dt
        k = dt / 3.6e6
        h["delta_soc_kwh"] += (soc - p[1]) / 100 * CAP_KWH
        if p[4] is not None: h["kwh_carga"] += p[4] * k
        if p[3] is not None and p[3] > BANDA_MUERTA_A: h["kwh_descarga"] += p[2] * p[3] * k
        h["kwh_pv"] += (p[5] or 0) * k; h["kwh_carga_ac"] += (p[6] or 0) * k; h["kwh_red"] += max(p[7] or 0, 0) * k
    filas = []
    for (inv, t), h in sorted(H.items()):
        from datetime import datetime, timezone
        filas.append([inv, datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00"), int(h["n"]),
                      round(h["seg_obs"]), round(h["seg_hueco"]), round(h["seg_soc_bajo"]),
                      round(h["soc_sum"] / h["n"], 2), h["soc_min"], h["soc_max"]] +
                     [round(h[c], 4) for c in ["kwh_carga", "kwh_descarga", "delta_soc_kwh", "kwh_pv", "kwh_carga_ac", "kwh_red"]])
    return filas, {k: dict(v) for k, v in dq.items()}

def cargar_pg(filas, dq):
    import psycopg
    dsn = (f"host={os.environ['POSTGRES_HOST']} port={os.getenv('POSTGRES_PORT', '5432')} dbname={os.environ['POSTGRES_DB']} "
           f"user={os.environ['POSTGRES_USER']} password={os.environ['POSTGRES_PASSWORD']}")
    buf = io.StringIO(); csv.writer(buf).writerows(filas); buf.seek(0)
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(7001)")           # evita cargas concurrentes
        cur.execute("CREATE TEMP TABLE stg (LIKE dw.fact_bateria_hora INCLUDING DEFAULTS) ON COMMIT DROP")
        with cur.copy(f"COPY stg ({','.join(COLS)}) FROM STDIN WITH (FORMAT csv)") as cp:
            cp.write(buf.read())
        sets = ",".join(f"{c}=EXCLUDED.{c}" for c in COLS[2:])
        cur.execute(f"INSERT INTO dw.fact_bateria_hora ({','.join(COLS)}) SELECT {','.join(COLS)} FROM stg "
                    f"ON CONFLICT (inverter_id, hora_utc) DO UPDATE SET {sets}")
        cur.execute("INSERT INTO dw.dim_fecha (fecha) SELECT DISTINCT hora_utc::date FROM dw.fact_bateria_hora ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO dw.etl_audit (fuente, filas_leidas, filas_validas, horas_cargadas, detalle) VALUES (%s,%s,%s,%s,%s)",
                    ("opencem csv", sum(d["leidas"] for d in dq.values()), sum(d["validas"] for d in dq.values()),
                     len(filas), json.dumps(dq)))

def main(origen, salida="."):
    filas, dq = extraer(origen)
    os.makedirs(salida, exist_ok=True)
    with open(os.path.join(salida, "fact_bateria_hora.csv"), "w", newline="") as o:
        w = csv.writer(o); w.writerow(COLS); w.writerows(filas)
    json.dump(dq, open(os.path.join(salida, "dq_resumen.json"), "w"), indent=1)
    print(json.dumps(dq, indent=1), f"\nhoras Silver: {len(filas)}")
    if os.getenv("POSTGRES_HOST"): cargar_pg(filas, dq); print("cargado a PostgreSQL")

if __name__ == "__main__":
    main(*sys.argv[1:])
