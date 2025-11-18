# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Sistem paketleri: docker CLI
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY api_py/requirements.txt /app/api_py/requirements.txt
RUN pip install --no-cache-dir -r /app/api_py/requirements.txt

# Uygulama
COPY api_py /app/api_py
COPY www /app/www
# Eğer www'yi host'tan volume vereceksen bu COPY'yi silebilirsin.
# Şimdilik kalsın, problem değil.

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["uvicorn", "api_py.app:app", "--host", "0.0.0.0", "--port", "8001"]
