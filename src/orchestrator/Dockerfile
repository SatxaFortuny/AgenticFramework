FROM python:3.11-slim

WORKDIR /app

# Here we create a system group and a user so we don't run with root.
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Here we copy everything from the src/orchestrator into /app
COPY . .

RUN mkdir -p /app/configs

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["python", "api.py"]
