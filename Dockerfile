FROM python:3.12-slim

# O pdfplumber puxa extensões em C (cryptography/cffi); a imagem slim já traz
# wheels para todas elas em 3.12, então nada precisa ser compilado aqui.
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY webapp/ ./webapp/
COPY config/ ./config/
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000

# Um worker só: o processamento é pesado em memória (~180 MB de pico) e roda
# em thread própria. Dois workers dobrariam o consumo sem ganho real, porque o
# uso é de poucos envios por dia.
CMD uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 120
