FROM python:3.12.12-alpine3.23@sha256:f47255bb0de452ac59afc49eaabe992720fe282126bb6a4f62de9dd3db1742dc

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apk add --no-cache jq=1.8.1-r0

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup -g 10001 tokentx && adduser -u 10001 -G tokentx -S tokentx
USER tokentx

COPY src/ /app/src/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health/ready || exit 1

ENTRYPOINT ["python", "src/main.py"]
