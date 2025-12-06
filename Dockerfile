FROM python:3.12.12-alpine3.23

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apk add --no-cache jq=1.8.1-r0

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup -g 10001 tokentx && adduser -u 10001 -G tokentx -S tokentx
USER tokentx

COPY src/ /app/src/

ENTRYPOINT ["python", "src/main.py"]
