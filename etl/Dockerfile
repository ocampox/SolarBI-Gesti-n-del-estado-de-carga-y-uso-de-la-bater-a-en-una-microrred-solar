# python:3.12-slim (~45 MB base): el ETL usa solo stdlib + psycopg; alpine daria problemas con wheels binarios.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY etl_bateria.py etl_contexto.py cargar_bronze.py simulate.py ./
RUN useradd -u 10001 app && chown -R app /app
USER app
CMD ["python", "-u", "cargar_bronze.py"]
