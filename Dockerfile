FROM node:20-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY pool/ ./pool/
RUN pip install --no-cache-dir -e .
COPY --from=frontend /build/dist ./frontend/dist
COPY config.example.yaml ./
EXPOSE 3333 8080
CMD ["btxpool", "-c", "/app/config.yaml"]