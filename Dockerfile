# syntax=docker/dockerfile:1

# ---- Этап сборки зависимостей ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Компиляторы нужны только здесь, в финальный образ не попадут
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Финальный образ ----
FROM python:3.11-slim

# libpq5 — рантайм-библиотека для psycopg2 (без заголовков и компиляторов)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /backend

COPY --from=builder /install /usr/local
COPY . .

RUN chmod +x /backend/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/backend/entrypoint.sh"]
