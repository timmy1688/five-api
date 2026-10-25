FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
WORKDIR /app
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DEFAULT_TIMEOUT=60 SECRETS_FILE=/var/lib/five-api/secrets.json
COPY requirements.lock ./
RUN pip install --no-cache-dir --no-compile --require-hashes -r requirements.lock
RUN groupadd --gid 10001 five && useradd --uid 10001 --gid five --no-create-home five && mkdir -p /var/lib/five-api && chown five:five /var/lib/five-api
COPY --chown=five:five ./ ./
USER 10001:10001
RUN python -c "import os, tempfile; assert os.geteuid() != 0; tempfile.TemporaryFile(dir='/var/lib/five-api').close()"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["sh", "-c", "python -m app.wait_for_services && aerich upgrade && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 30"]
