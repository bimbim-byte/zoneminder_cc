FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir paho-mqtt requests urllib3

COPY main.py .

RUN mkdir -p /app/data

CMD ["python", "main.py"]
