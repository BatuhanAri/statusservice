# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Bağımlılıklar
COPY api_py/requirements.txt /app/api_py/requirements.txt
RUN pip install --no-cache-dir -r /app/api_py/requirements.txt

# Uygulama
COPY api_py /app/api_py
# WWW klasörünü host’tan volume olarak vereceğiz (build’e koymuyoruz)

ENV PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "api_py.app:app", "--host", "0.0.0.0", "--port", "8001"]
