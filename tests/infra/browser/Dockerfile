FROM mcr.microsoft.com/playwright/python:v1.65.1-noble@sha256:0ab41a37431309d72b7a26f40ef1fdb464a62740196b2143965a2f59dc090409
WORKDIR /opt/palimpsest-browser
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY png_fixture.py ./png_fixture.py
COPY browser_acceptance.py ./browser_acceptance.py
ENTRYPOINT ["python", "browser_acceptance.py"]
