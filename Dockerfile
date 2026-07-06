# Etapa 1: build del frontend
FROM node:22-alpine AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Etapa 2: backend + estáticos
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY bot/ bot/
COPY api/ api/
COPY config/ config/
RUN pip install --no-cache-dir .
COPY --from=web /app/web/dist web/dist

ENV BOT_DATA_DIR=/data
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
