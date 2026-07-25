FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir pip -U

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "aerich upgrade && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '127.0.0.1,172.16.0.0/12'"]
