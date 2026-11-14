FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEOWIKI_RESEARCH_ROOT=/var/lib/neowiki \
    HF_HOME=/var/lib/neowiki/model-cache/huggingface \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 neowiki \
    && useradd --uid 10001 --gid 10001 --no-create-home neowiki \
    && mkdir -p /var/lib/neowiki/data /var/lib/neowiki/model-cache \
    && chown -R neowiki:neowiki /var/lib/neowiki
COPY requirements.docker.txt ./
RUN python -m pip install --no-cache-dir -r requirements.docker.txt
COPY *.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY deploy/ ./deploy/
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "deploy/runtime.py"]
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=1", "--threads=4", "--timeout=120", "--access-logfile=-", "--error-logfile=-", "deploy.wsgi:app"]
