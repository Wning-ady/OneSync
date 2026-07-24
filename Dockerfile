ARG ONEDRIVE_BASE_DIGEST=sha256:263a90247b1106d1f0df3b541ed01a45d0c63837cba40e50108b0d80222541ae
FROM driveone/onedrive:edge@${ONEDRIVE_BASE_DIGEST} AS python-builder

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /tmp/requirements.lock
RUN python3 -m venv /opt/onesync \
    && /opt/onesync/bin/python -m pip install \
        --no-cache-dir \
        --require-hashes \
        -r /tmp/requirements.lock

FROM python-builder AS test

WORKDIR /src
COPY requirements-dev.lock /tmp/requirements-dev.lock
RUN /opt/onesync/bin/python -m pip install \
        --no-cache-dir \
        --require-hashes \
        -r /tmp/requirements-dev.lock
COPY app ./app
COPY tests ./tests
RUN /opt/onesync/bin/python -m pytest -q

FROM python-builder AS python-runtime

RUN rm -f /opt/onesync/bin/pip /opt/onesync/bin/pip3 /opt/onesync/bin/pip3.* \
    && find /opt/onesync/lib -type d -path '*/site-packages/pip' -prune -exec rm -rf {} + \
    && find /opt/onesync/lib -type d -path '*/site-packages/pip-*.dist-info' -prune -exec rm -rf {} + \
    && find /opt/onesync/lib -type d -path '*/site-packages/setuptools*' -prune -exec rm -rf {} + \
    && find /opt/onesync/lib -type d -path '*/site-packages/wheel*' -prune -exec rm -rf {} +

FROM driveone/onedrive:edge@${ONEDRIVE_BASE_DIGEST}

ARG APP_VERSION=0.1.4

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=python-runtime /opt/onesync /opt/onesync
COPY app ./app
RUN chmod -R a+rX /app/app
COPY docker/entrypoint.sh /usr/local/bin/onesync
RUN chmod 0755 /usr/local/bin/onesync

ENV PATH=/opt/onesync/bin:$PATH \
    APP_CONFIG_DIR=/onedrive/conf \
    ONESYNC_VERSION=${APP_VERSION} \
    ONEDRIVE_DATA_DIR=/onedrive/data \
    GRAPH_TENANT_ID=5dldn8.onmicrosoft.com \
    TZ=Asia/Shanghai \
    PUID=99 \
    PGID=100
EXPOSE 8098
VOLUME ["/onedrive/conf", "/onedrive/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8098/api/health', timeout=3)"
ENTRYPOINT ["/usr/local/bin/onesync"]
