"""Check minimo: python tests/test_etl.py  (CSV sintetico: decodificacion uint16 de corriente, carga/descarga, banda muerta, hueco)."""
import csv, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
import etl_bateria as e

H = "read_ts,inverter,battvolt,battcurr,battsoc,battchgpower,pv1power,outsumw,gridpowerw_a"
rows = [  # ts, V, I(raw), soc, chgW
    (0, 50, 6543.6, 50, 500), (10, 50, 6543.6, 50, 500),     # I=-10 A -> carga 500 W durante 10 s
    (20, 50, 10.0, 50, 0),                                   # +10 A -> descarga 500 W (intervalo 10-20 s usa lectura previa)
    (30, 50, 0.5, 50, 0),                                    # dentro de banda muerta -> no cuenta
    (5000, 50, 10.0, 49, 0)]                                 # hueco > GAP_MAX_S -> no integra
d = tempfile.mkdtemp()
with open(os.path.join(d, "a.csv"), "w", newline="") as f:
    f.write(H + "\n")
    for t, v, i, s, c in rows:
        f.write(f"{t},1,{v},{i},{s},{c},0,0,0\n")
filas, dq = e.extraer(d)
r = dict(zip(e.COLS, filas[0]))
assert dq[1]["R3_corriente_decodificada"] == 2, dq
assert abs(r["kwh_carga"] - 500 * 20 / 3.6e6) < 1e-4, r          # 2 intervalos de 10 s a 500 W
assert abs(r["kwh_descarga"] - 500 * 10 / 3.6e6) < 1e-4, r       # solo el intervalo con I=+10 A
assert r["n_lecturas"] == 4 and dict(zip(e.COLS, filas[1]))["seg_hueco"] > 0, filas
print("OK")
