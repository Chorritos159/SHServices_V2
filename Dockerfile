# =====================================================================
# Dockerfile UNIVERSAL para los 7 microservicios FastAPI de SHServices
# ---------------------------------------------------------------------
# Todos los servicios comparten la misma estructura interna:
#   <servicio>/
#     requirements.txt
#     app/  (paquete con app.main:app)
#
# Se construye pasando cada carpeta de servicio como "context":
#   build:
#     context: ./ticket_service
#     dockerfile: ../Dockerfile
#
# Puerto interno FIJO = 80 (así lo espera el Gateway: http://ticket-service:80)
# =====================================================================
FROM python:3.11-slim

# ---- Buenas prácticas de runtime -----------------------------------
# PYTHONDONTWRITEBYTECODE: no genera archivos .pyc (imagen más limpia)
# PYTHONUNBUFFERED:        logs salen en tiempo real (vital para Docker)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- Capa de dependencias (se cachea si requirements.txt no cambia) --
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Código de la aplicación ---------------------------------------
# Copiamos SOLO la carpeta app/ (nunca el venv local ni .pyc)
COPY ./app ./app

# ---- Usuario sin privilegios (endurecimiento de seguridad) ----------
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80

# ---- Health check nativo (sin curl; usamos el propio Python) --------
HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=15s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:80/api/v1/health').status==200 else 1)"

# ---- Arranque uniforme para los 7 servicios -------------------------
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
