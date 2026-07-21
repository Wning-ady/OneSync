FROM driveone/onedrive:edge

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt
COPY app ./app
RUN chmod -R a+rX /app/app
COPY docker/entrypoint.sh /usr/local/bin/onesync
RUN chmod 0755 /usr/local/bin/onesync

ENV APP_CONFIG_DIR=/onedrive/conf \
    ONEDRIVE_DATA_DIR=/onedrive/data \
    GRAPH_TENANT_ID=5dldn8.onmicrosoft.com \
    TZ=Asia/Shanghai \
    PUID=99 \
    PGID=100
EXPOSE 8098
VOLUME ["/onedrive/conf", "/onedrive/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8098/api/health', timeout=3)"
ENTRYPOINT ["/usr/local/bin/onesync"]
