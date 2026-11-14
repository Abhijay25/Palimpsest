FROM python:3.12.12-slim-bookworm
WORKDIR /opt/palimpsest
COPY infra/data/tooling/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt
COPY scripts/palimpsest_data ./palimpsest_data
COPY datasets.lock.json ./datasets.lock.json
ENTRYPOINT ["python", "-m", "palimpsest_data.parquet_worker"]
