FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ ./scripts/

# Credentials are NOT baked into the image — docker-compose.yml passes them in
# at runtime via `env_file: config.env`. The container idles so you can run
# commands against it interactively:
#   docker exec -it tuya-control python scripts/tuya-cli.py list
CMD ["tail", "-f", "/dev/null"]
