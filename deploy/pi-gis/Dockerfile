# syntax=docker/dockerfile:1
FROM debian:trixie-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG QGIS_PLUGIN_VERSION=0.4.9
ARG QGIS_PLUGIN_SHA256=29e00813d79b96253c5d232cfc512a9d6d528faad80ff92319cb7d7fcf0dc26c

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    QT_QPA_PLATFORM=offscreen \
    QGIS_PLUGINPATH=/opt/qgis-plugins \
    QGIS_MCP_MAX_PENDING=20 \
    QGIS_MCP_CONTROL_RESERVE=4 \
    QGIS_MCP_QUEUE_DEADLINE_SECONDS=300

RUN printf '%s\n' \
        'deb http://deb.debian.org/debian trixie-backports main' \
        > /etc/apt/sources.list.d/trixie-backports.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends -t trixie-backports \
        ca-certificates \
        curl \
        gdal-bin \
        grass-core \
        procps \
        python3-fastapi \
        python3-gdal \
        python3-pydantic \
        python3-uvicorn \
        qgis \
        qgis-plugin-grass \
        time \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xauth \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --silent --show-error \
        "https://plugins.qgis.org/plugins/qgis_agent_mcp/version/${QGIS_PLUGIN_VERSION}/download/" \
        --output /tmp/qgis_agent_mcp.zip \
    && printf '%s  %s\n' "${QGIS_PLUGIN_SHA256}" /tmp/qgis_agent_mcp.zip \
        | sha256sum --check --strict \
    && mkdir -p /opt/qgis-plugins \
    && unzip -q /tmp/qgis_agent_mcp.zip -d /opt/qgis-plugins \
    && rm /tmp/qgis_agent_mcp.zip

COPY deploy/pi-gis/QGIS3.ini /opt/scout-qgis/profile/QGIS/QGIS3.ini
COPY deploy/pi-gis/launch-qgis-mcp.sh /usr/local/bin/scout-qgis-mcp

RUN chmod 0755 /usr/local/bin/scout-qgis-mcp

WORKDIR /work

CMD ["scout-qgis-mcp"]
