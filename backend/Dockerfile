FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 quota-watch \
    && useradd --uid 10001 --gid quota-watch --create-home quota-watch

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && mkdir -p /data \
    && chown quota-watch:quota-watch /data

USER quota-watch
EXPOSE 8787

CMD ["uvicorn", "quota_watch.server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers", "--forwarded-allow-ips", "*", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
