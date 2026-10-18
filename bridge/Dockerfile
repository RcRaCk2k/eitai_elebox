FROM python:3.12-slim

# libusb for ZLG adapters, iproute2 to verify SocketCAN listen-only mode
RUN apt-get update && apt-get install -y --no-install-recommends libusb-1.0-0 iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir paho-mqtt==2.1.0

COPY lib /src/lib
RUN pip install --no-cache-dir /src/lib

COPY bridge/eitai_elebox_bridge /app/eitai_elebox_bridge
WORKDIR /app
CMD ["python", "-m", "eitai_elebox_bridge"]
