FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
WORKDIR /opt/palimpsest
COPY infra/data/tooling/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt
COPY scripts/palimpsest_data ./palimpsest_data
COPY datasets.lock.json ./datasets.lock.json
ENTRYPOINT ["python", "-m", "palimpsest_data.parquet_worker"]
