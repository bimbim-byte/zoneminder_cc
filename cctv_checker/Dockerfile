FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

# Install paho-mqtt jika dibutuhkan
RUN pip install --no-cache-dir paho-mqtt

# Copy file worker ke container
COPY mqtt_file_logger.py .

# Buat folder data untuk mount volume tempat menyimpan file JSON
RUN mkdir -p /app/data

CMD ["python", "mqtt_file_logger.py"]
