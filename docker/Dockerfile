ARG GEOTRELLIS_EXTENSIONS_VERSION=1.4.0-SNAPSHOT
ARG GEOTRELLIS_BACKEND_ASSEMBLY_VERSION=0.4.5
ARG JMX_PROMETHEUS_JAVAAGENT_VERSION=0.13.0

FROM centos:7 as downloader

ARG GEOTRELLIS_EXTENSIONS_VERSION
ARG GEOTRELLIS_BACKEND_ASSEMBLY_VERSION
ARG JMX_PROMETHEUS_JAVAAGENT_VERSION

WORKDIR /opt

RUN yum install -y git && \
    git clone https://github.com/Open-EO/openeo-geopyspark-integrationtests.git openeo && \
    curl -O https://artifactory.vgt.vito.be/auxdata-public/openeo/geotrellis-backend-assembly-${GEOTRELLIS_BACKEND_ASSEMBLY_VERSION}-openeo.jar && \
    curl -O https://artifactory.vgt.vito.be/libs-snapshot-public/org/openeo/geotrellis-extensions/${GEOTRELLIS_EXTENSIONS_VERSION}/geotrellis-extensions-${GEOTRELLIS_EXTENSIONS_VERSION}.jar && \
    curl -O https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/${JMX_PROMETHEUS_JAVAAGENT_VERSION}/jmx_prometheus_javaagent-${JMX_PROMETHEUS_JAVAAGENT_VERSION}.jar

FROM gcr.io/spark-operator/spark-py:v2.4.5

ARG GEOTRELLIS_EXTENSIONS_VERSION
ARG GEOTRELLIS_BACKEND_ASSEMBLY_VERSION
ARG JMX_PROMETHEUS_JAVAAGENT_VERSION

LABEL maintainer="VITO Remote Sensing"

RUN printf '[global]\nindex = https://artifactory.vgt.vito.be/api/pypi/python-packages\nextra-index-url = https://artifactory.vgt.vito.be/api/pypi/python-packages/simple' > /etc/pip.conf

COPY --from=downloader /opt/openeo /tmp/openeo
COPY --from=downloader /opt/geotrellis-backend-assembly-${GEOTRELLIS_BACKEND_ASSEMBLY_VERSION}-openeo.jar /opt
COPY --from=downloader /opt/geotrellis-extensions-${GEOTRELLIS_EXTENSIONS_VERSION}.jar /opt
COPY --from=downloader /opt/jmx_prometheus_javaagent-${JMX_PROMETHEUS_JAVAAGENT_VERSION}.jar /opt

COPY creo_layercatalog.json /opt/layercatalog.json

RUN python3 -m pip install -I --upgrade pip && \
    python3 -m pip install -r /tmp/openeo/requirements.txt && \
    python3 -m pip install kazoo==2.7.0 py4j && \
    rm -rf /tmp/openeo && \
    rm -rf /root/.cache && \
    rm -rf /var/cache/apt/*
