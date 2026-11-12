FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv ca-certificates poppler-utils libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-web.txt ./
COPY web/package.json web/package-lock.json web/
RUN python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-web.txt \
    && npm --prefix web ci
COPY . .
RUN ./scripts/install_website.sh
EXPOSE 5174
CMD ["./scripts/run_website.sh"]
