"""Genera el proyecto Power BI (PBIP + TMDL + PBIR) en ../powerbi. Uso: python gen_powerbi.py"""
import json, os

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "powerbi")
SM, RP = f"{R}/SolarBI.SemanticModel", f"{R}/SolarBI.Report"
T = "\t"
SCH = "https://developer.microsoft.com/json-schemas/fabric/"


def w(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)


def j(p, o):
    w(p, json.dumps(o, indent=2))


def platform(kind):
    return {"$schema": SCH + "gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": "SolarBI"},
            "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-00000000000" + ("1" if kind == "SemanticModel" else "2")}}


j(f"{R}/SolarBI.pbip", {"version": "1.0", "artifacts": [{"report": {"path": "SolarBI.Report"}}], "settings": {"enableAutoRecovery": True}})
j(f"{SM}/definition.pbism", {"version": "4.2", "settings": {}})
j(f"{SM}/.platform", platform("SemanticModel"))
w(f"{SM}/definition/database.tmdl", "database SolarBI\n\tcompatibilityLevel: 1600\n")
w(f"{SM}/definition/model.tmdl", "model Model\n\tculture: es-CO\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\n"
  "ref table fact_bateria_hora\nref table dim_inversor\nref table dim_fecha\nref table dim_estado_soc\n"
  "ref table 'Param Tarifa'\nref table 'Param Capacidad'\n")
w(f"{SM}/definition/relationships.tmdl",
  "relationship r_fact_inversor\n\tfromColumn: fact_bateria_hora.inverter_id\n\ttoColumn: dim_inversor.inverter_id\n\n"
  "relationship r_fact_fecha\n\tfromColumn: fact_bateria_hora.fecha\n\ttoColumn: dim_fecha.fecha\n")


def col(n, t, fmt=None, extra=""):
    s = f"{T}column {n}\n{T}{T}dataType: {t}\n"
    if fmt:
        s += f"{T}{T}formatString: {fmt}\n"
    return s + f"{extra}{T}{T}summarizeBy: none\n{T}{T}sourceColumn: {n}\n\n"


def pg(table, extra_steps=""):
    return (f"{T}partition {table} = m\n{T}{T}mode: import\n{T}{T}source =\n{T}{T}{T}let\n"
            f'{T}{T}{T}{T}Origen = PostgreSQL.Database("localhost:5433", "solar_db"),\n'
            f'{T}{T}{T}{T}T = Origen{{[Schema="dw", Item="{table}"]}}[Data]{extra_steps}\n'
            f"{T}{T}{T}in\n{T}{T}{T}{T}{'Fecha' if extra_steps else 'T'}\n")


M = [("SoC Prom %", "DIVIDE(SUMX(fact_bateria_hora, fact_bateria_hora[soc_prom] * fact_bateria_hora[seg_obs]), SUM(fact_bateria_hora[seg_obs]))", "0.0"),
     ("SoC Min %", "MIN(fact_bateria_hora[soc_min])", "0.0"),
     ("% Tiempo SoC Bajo", "DIVIDE(SUM(fact_bateria_hora[seg_soc_bajo]), SUM(fact_bateria_hora[seg_obs]))", "0.00%"),
     ("kWh Carga", "SUM(fact_bateria_hora[kwh_carga])", "#,0.0"),
     ("kWh Descarga", "SUM(fact_bateria_hora[kwh_descarga])", "#,0.0"),
     ("kWh PV", "SUM(fact_bateria_hora[kwh_pv])", "#,0.0"),
     ("kWh Red", "SUM(fact_bateria_hora[kwh_red])", "#,0.0"),
     ("Eficiencia Ida y Vuelta", "DIVIDE([kWh Descarga], [kWh Carga] - SUM(fact_bateria_hora[delta_soc_kwh]))", "0.000"),
     ("Ciclos Equivalentes", "DIVIDE([kWh Descarga], SELECTEDVALUE('Param Capacidad'[Capacidad kWh], 10.24) * DISTINCTCOUNT(fact_bateria_hora[inverter_id]))", "0.0"),
     ("Autosuficiencia %", "1 - DIVIDE([kWh Red], SUM(fact_bateria_hora[kwh_carga_ac]))", "0.0%"),
     ("Disponibilidad Registro", "DIVIDE(SUM(fact_bateria_hora[seg_obs]), SUM(fact_bateria_hora[seg_obs]) + SUM(fact_bateria_hora[seg_hueco]))", "0.0%"),
     ("Ahorro COP", "[kWh Descarga] * SELECTEDVALUE('Param Tarifa'[Tarifa COP/kWh], 850)", "#,0"),
     ("kWh Descarga Mes Anterior", "CALCULATE([kWh Descarga], DATEADD(dim_fecha[fecha], -1, MONTH))", "#,0.0"),
     ("Var kWh Descarga vs Mes Ant %", "DIVIDE([kWh Descarga] - [kWh Descarga Mes Anterior], [kWh Descarga Mes Anterior])", "0.0%"),
     ("kWh Descarga YTD", "TOTALYTD([kWh Descarga], dim_fecha[fecha])", "#,0.0")]
fact = "table fact_bateria_hora\n\n" + "".join(f"{T}measure '{n}' = {d}\n{T}{T}formatString: {f}\n\n" for n, d, f in M)
for n, t, f in [("inverter_id", "int64", None), ("hora_utc", "dateTime", "dd/mm/yyyy hh:nn"), ("n_lecturas", "int64", None), ("seg_obs", "int64", None),
                ("seg_hueco", "int64", None), ("seg_soc_bajo", "int64", None), ("soc_prom", "double", "0.00"), ("soc_min", "double", "0.00"),
                ("soc_max", "double", "0.00"), ("kwh_carga", "double", None), ("kwh_descarga", "double", None), ("delta_soc_kwh", "double", None),
                ("kwh_pv", "double", None), ("kwh_carga_ac", "double", None), ("kwh_red", "double", None), ("fecha", "dateTime", "dd/mm/yyyy")]:
    fact += col(n, t, f)
fact += pg("fact_bateria_hora", ',\n' + f'{T}{T}{T}{T}Fecha = Table.AddColumn(T, "fecha", each Date.From(DateTimeZone.RemoveZone([hora_utc])), type date)')
w(f"{SM}/definition/tables/fact_bateria_hora.tmdl", fact)
w(f"{SM}/definition/tables/dim_inversor.tmdl", "table dim_inversor\n\n" + "".join(col(n, t) for n, t in
  [("inverter_id", "int64"), ("nombre", "string"), ("capacidad_kwh", "double"), ("paneles", "int64"), ("potencia_inversor_kw", "double")]) + pg("dim_inversor"))
w(f"{SM}/definition/tables/dim_estado_soc.tmdl", "table dim_estado_soc\n\n" + "".join(col(n, t) for n, t in
  [("estado_key", "int64"), ("estado", "string"), ("soc_desde", "double"), ("soc_hasta", "double")]) + pg("dim_estado_soc"))
w(f"{SM}/definition/tables/dim_fecha.tmdl", "table dim_fecha\n\tdataCategory: Time\n\n" +
  col("fecha", "dateTime", "dd/mm/yyyy", extra=f"{T}{T}isKey\n") + "".join(col(n, "int64") for n in ["anio", "mes", "dia_semana"]) + pg("dim_fecha"))
for name, colname, rng, typ in [("Param Tarifa", "Tarifa COP/kWh", "500, 1500, 50", "int64"), ("Param Capacidad", "Capacidad kWh", "5, 30, 1", "double")]:
    w(f"{SM}/definition/tables/{name}.tmdl", f"table '{name}'\n\n{T}column '{colname}'\n{T}{T}dataType: {typ}\n{T}{T}summarizeBy: none\n{T}{T}sourceColumn: [Value]\n\n"
      f"{T}partition '{name}' = calculated\n{T}{T}mode: import\n{T}{T}source = GENERATESERIES({rng})\n")

# ---- Reporte PBIR (3 paginas)
j(f"{RP}/definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": "../SolarBI.SemanticModel"}}})
j(f"{RP}/.platform", platform("Report"))
D = f"{RP}/definition"
j(f"{D}/version.json", {"$schema": SCH + "item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
j(f"{D}/report.json", {"$schema": SCH + "item/report/definition/report/2.0.0/schema.json",
                         "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.61", "type": "SharedResources"}}})
j(f"{D}/pages/pages.json", {"$schema": SCH + "item/report/definition/pagesMetadata/1.0.0/schema.json", "pageOrder": ["p1", "p2", "p3"], "activePageName": "p1"})


def ref(kind, e, n):
    return {"field": {kind: {"Expression": {"SourceRef": {"Entity": e}}, "Property": n}}, "queryRef": f"{e}.{n}", "nativeQueryRef": n}


F = "fact_bateria_hora"
mea = lambda n: ref("Measure", F, n)
cl = lambda e, n: ref("Column", e, n)


def page(pid, name):
    j(f"{D}/pages/{pid}/page.json", {"$schema": SCH + "item/report/definition/page/2.0.0/schema.json", "name": pid, "displayName": name,
                                      "displayOption": "FitToPage", "height": 720, "width": 1280})


def vis(pg_, vid, typ, x, y, wd, h, title, **roles):
    j(f"{D}/pages/{pg_}/visuals/{vid}/visual.json", {
        "$schema": SCH + "item/report/definition/visualContainer/2.0.0/schema.json", "name": vid,
        "position": {"x": x, "y": y, "z": 0, "height": h, "width": wd},
        "visual": {"visualType": typ, "query": {"queryState": {r: {"projections": p} for r, p in roles.items()}},
                   "objects": {"title": [{"properties": {"text": {"expr": {"Literal": {"Value": "'" + title + "'"}}}}}]},
                   "drillFilterOtherVisuals": True}})


page("p1", "1. Estado de la bateria"); page("p2", "2. Uso y balance energetico"); page("p3", "3. Calidad y escenarios")
vis("p1", "s1", "slicer", 20, 10, 250, 70, "Inversor", Values=[cl("dim_inversor", "nombre")])
vis("p1", "s2", "slicer", 290, 10, 250, 70, "Ano", Values=[cl("dim_fecha", "anio")])
for i, m in enumerate(["SoC Prom %", "SoC Min %", "% Tiempo SoC Bajo", "Ciclos Equivalentes"]):
    vis("p1", f"c{i}", "card", 20 + i * 310, 100, 290, 110, m, Values=[mea(m)])
vis("p1", "l1", "lineChart", 20, 230, 1240, 470, "SoC promedio diario por inversor", Category=[cl("dim_fecha", "fecha")], Y=[mea("SoC Prom %")], Series=[cl("dim_inversor", "nombre")])
for i, m in enumerate(["kWh Descarga", "kWh Carga", "Autosuficiencia %"]):
    vis("p2", f"k{i}", "card", 20 + i * 320, 10, 300, 100, m, Values=[mea(m)])
vis("p2", "b1", "clusteredColumnChart", 20, 130, 620, 560, "Balance energetico por mes: PV, red, carga y descarga", Category=[cl("dim_fecha", "mes")],
    Y=[mea("kWh PV"), mea("kWh Red"), mea("kWh Carga"), mea("kWh Descarga")])
vis("p2", "b2", "lineChart", 660, 130, 600, 560, "Descarga vs mes anterior", Category=[cl("dim_fecha", "fecha")], Y=[mea("kWh Descarga"), mea("kWh Descarga Mes Anterior")])
for i, m in enumerate(["Disponibilidad Registro", "Eficiencia Ida y Vuelta", "Ahorro COP"]):
    vis("p3", f"q{i}", "card", 20 + i * 320, 10, 300, 100, m, Values=[mea(m)])
vis("p3", "w1", "slicer", 20, 130, 300, 120, "Escenario: tarifa COP/kWh", Values=[cl("Param Tarifa", "Tarifa COP/kWh")])
vis("p3", "w2", "slicer", 340, 130, 300, 120, "Escenario: capacidad kWh por banco", Values=[cl("Param Capacidad", "Capacidad kWh")])
vis("p3", "t1", "tableEx", 20, 270, 1240, 430, "Auditoria por inversor",
    Values=[cl("dim_inversor", "nombre"), mea("kWh Carga"), mea("kWh Descarga"), mea("Eficiencia Ida y Vuelta"), mea("Disponibilidad Registro")])
print("ok")
