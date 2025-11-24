# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd \
      libsystemd0 \
      libgcrypt20 \
      liblz4-1 \
      liblzma5 \
      libzstd1 \
      libcap2 \
      dbus \
      && rm -rf /var/lib/apt/lists/*

# Python bağımlılıklarını kur
COPY api_py/requirements.txt /app/api_py/requirements.txt
RUN pip install --no-cache-dir -r /app/api_py/requirements.txt

# Uygulama kodları
COPY api_py /app/api_py
COPY www /app/www

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["uvicorn", "api_py.app:app", "--host", "0.0.0.0", "--port", "8001"]
