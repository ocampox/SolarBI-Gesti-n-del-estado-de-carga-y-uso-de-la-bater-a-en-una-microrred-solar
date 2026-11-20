"""ETL de contexto OpenCEM: minimiza el JSON antes de Gold.

No persiste ``textual_description``: puede identificar actividades/personas. Conserva
solo fuente, intervalo y duracion, suficientes para correlacionar carga y contexto.
Uso: python etl_contexto.py <bronze.sqlite> [salida_dir]. Con POSTGRES_HOST carga Gold.
"""
import csv, json, os, sqlite3, sys
from datetime import datetime, timezone

COLS = ["contexto_id", "recorded_utc", "inicio_utc", "fin_utc", "fuente", "duracion_min"]

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

def extraer(sqlite_path):
    con = sqlite3.connect(f"file:{os.path.abspath(sqlite_path)}?mode=ro", uri=True)
    try:
        filas = []
        for ident, recorded, inicio, fin, value in con.execute("SELECT id,recorded,start,end,value FROM context ORDER BY id"):
            payload = json.loads(value or "{}")
            # Minimizacion Ley 1581: descarta toda descripcion libre antes de salir de Bronze.
            fuente = str(payload.get("source", "sin fuente"))[:80]
            filas.append([ident, iso(recorded), iso(inicio), iso(fin), fuente, round((fin-inicio)/60, 2)])
        return filas
    finally:
        con.close()

def cargar_pg(filas):
    import psycopg
    dsn = f"host={os.environ['POSTGRES_HOST']} port={os.getenv('POSTGRES_PORT','5432')} dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']} password={os.environ['POSTGRES_PASSWORD']}"
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.executemany("""INSERT INTO dw.fact_contexto_minimo (contexto_id,recorded_utc,inicio_utc,fin_utc,fuente,duracion_min)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (contexto_id) DO UPDATE SET
            recorded_utc=EXCLUDED.recorded_utc,inicio_utc=EXCLUDED.inicio_utc,fin_utc=EXCLUDED.fin_utc,fuente=EXCLUDED.fuente,duracion_min=EXCLUDED.duracion_min""", filas)
        cur.execute("INSERT INTO dw.etl_audit (fuente,filas_leidas,filas_validas,horas_cargadas,detalle) VALUES (%s,%s,%s,%s,%s)",
                    ("opencem context JSON minimizado", len(filas), len(filas), 0, json.dumps({"atributo_excluido":"textual_description"})))

def main(origen, salida="."):
    filas = extraer(origen); os.makedirs(salida, exist_ok=True)
    with open(os.path.join(salida, "contexto_minimo.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(COLS); w.writerows(filas)
    if os.getenv("POSTGRES_HOST"): cargar_pg(filas)
    print(json.dumps({"contextos_minimizados": len(filas), "atributo_excluido": "textual_description"}))

if __name__ == "__main__":
    main(*sys.argv[1:])
