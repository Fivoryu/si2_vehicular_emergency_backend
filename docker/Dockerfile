# Build stage
FROM python:3.11-slim as builder

WORKDIR /tmp

# Instalar dependencias para compilar
RUN apt-get update && apt-get install -y \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Crear wheelhouse para cached builds
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /tmp/wheels -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Metadatos
LABEL maintainer="Asistencia Vehicular <dev@asistencia-vehicular.com>"
LABEL version="1.0"
LABEL description="FastAPI Backend - Sistema de Asistencia Vehicular"

# Instalar dependencias runtime
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar wheels desde builder
COPY --from=builder /tmp/wheels /wheels
COPY --from=builder /tmp/requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache /wheels/* && rm -rf /wheels

# Copiar código aplicación
COPY app /app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Variables de entorno por defecto
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBUG=False

# Puerto
EXPOSE 8000

# Usuario no-root para seguridad
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Comando de inicio
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
