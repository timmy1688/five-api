FROM node:20-alpine AS frontend

# 国内构建可传 https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry="$NPM_REGISTRY"
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# 国内构建可传 https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_DEFAULT_TIMEOUT=60

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt

COPY backend/ .
COPY --from=frontend /src/dist ./static

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["sh", "-c", "python -m app.wait_for_services && aerich upgrade && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --timeout-graceful-shutdown 30"]
