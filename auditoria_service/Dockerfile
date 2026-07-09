# Usamos una imagen oficial y ligera de Python
FROM python:3.11-slim

# Evita que Python genere archivos .pyc y asegura que los logs salgan directo a la consola
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Directorio de trabajo dentro del contenedor
WORKDIR /code

# Copiamos primero las dependencias para aprovechar el caché de Docker
COPY ./requirements.txt /code/requirements.txt

# Instalamos las librerías
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copiamos el código fuente de la aplicación
COPY ./app /code/app

# El comando por defecto para arrancar
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]