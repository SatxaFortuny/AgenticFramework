FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r appgroup && useradd -r -g appgroup appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY servers/ ./servers/

RUN chown -R appuser:appgroup /app
USER appuser

ENV SERVER_SCRIPT=weather_server.py
CMD python servers/${SERVER_SCRIPT}