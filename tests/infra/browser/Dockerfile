FROM mcr.microsoft.com/playwright/python:v1.65.1-noble
WORKDIR /opt/palimpsest-browser
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY browser_acceptance.py ./browser_acceptance.py
ENTRYPOINT ["python", "browser_acceptance.py"]
