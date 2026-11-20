"""Ejecuta las dos cargas Gold a partir de la única Bronze SQLite."""
import os
from etl_bateria import main as cargar_telemetria
from etl_contexto import main as cargar_contexto

origen = os.getenv("BRONZE_SQLITE", "/data/opencem-v1.0.0.sqlite")
cargar_telemetria(origen, os.getenv("OUTPUT_DIR", "/tmp/solarbi"))
cargar_contexto(origen, os.getenv("OUTPUT_DIR", "/tmp/solarbi"))
