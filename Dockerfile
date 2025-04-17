FROM python:3.11-alpine
WORKDIR /app
RUN apk add --no-cache gcc musl-dev libffi-dev && pip install --no-cache-dir --upgrade pip
COPY requirements.txt .

RUN pip install -r requirements.txt
COPY . .

ENV ES_HOST=https://elasticsearch:9200
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000
ENV ES_VERIFY_CERTS=1

CMD ["python3", "main.py"]