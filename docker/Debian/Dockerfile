ARG GEOTRELLIS_EXTENSIONS_VERSION=2.2.0-SNAPSHOT
ARG GEOTRELLIS_BACKEND_ASSEMBLY_VERSION=0.4.7
ARG JMX_PROMETHEUS_JAVAAGENT_VERSION=0.13.0

FROM centos:7 as downloader

ARG GEOTRELLIS_EXTENSIONS_VERSION
ARG GEOTRELLIS_BACKEND_ASSEMBLY_VERSION
ARG JMX_PROMETHEUS_JAVAAGENT_VERSION

WORKDIR /opt

RUN curl -O https://artifactory.vgt.vito.be/auxdata-public/openeo/geotrellis-backend-assembly-${GEOTRELLIS_BACKEND_ASSEMBLY_VERSION}-openeo.jar && \
    curl -O https://artifactory.vgt.vito.be/libs-snapshot-public/org/openeo/geotrellis-extensions/${GEOTRELLIS_EXTENSIONS_VERSION}/geotrellis-extensions-${GEOTRELLIS_EXTENSIONS_VERSION}.jar && \
    curl -O https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/${JMX_PROMETHEUS_JAVAAGENT_VERSION}/jmx_prometheus_javaagent-${JMX_PROMETHEUS_JAVAAGENT_VERSION}.jar

FROM gcr.io/spark-operator/spark-py:v2.4.5

ARG GEOTRELLIS_EXTENSIONS_VERSION
ARG GEOTRELLIS_BACKEND_ASSEMBLY_VERSION
ARG JMX_PROMETHEUS_JAVAAGENT_VERSION

LABEL maintainer="VITO Remote Sensing"

RUN printf '[global]\nindex = https://artifactory.vgt.vito.be/api/pypi/python-packages\nextra-index-url = https://artifactory.vgt.vito.be/api/pypi/python-packages/simple' > /etc/pip.conf

COPY --from=downloader /opt/geotrellis-backend-assembly-${GEOTRELLIS_BACKEND_ASSEMBLY_VERSION}-openeo.jar /opt
COPY --from=downloader /opt/geotrellis-extensions-${GEOTRELLIS_EXTENSIONS_VERSION}.jar /opt
COPY --from=downloader /opt/jmx_prometheus_javaagent-${JMX_PROMETHEUS_JAVAAGENT_VERSION}.jar /opt

COPY docker/creo_layercatalog.json /opt/layercatalog.json
COPY docker/log4j.properties /opt/spark/conf/log4j.properties

RUN echo "deb [trusted=yes] https://artifactory.vgt.vito.be/GDAL-3.1.0 buster main" >> /etc/apt/sources.list && \
    echo "deb [trusted=yes] https://artifactory.vgt.vito.be/vito-deb-buster-public buster main" >> /etc/apt/sources.list && \
    apt-get --allow-releaseinfo-change update && \
    apt-get install -y libgdal27 gdal-bin gdal-data proj-bin orfeo-toolbox openeo-vito-aux-data && \
    python3 -m pip install -I --upgrade pip==20.2.4 && \
    python3 -m pip install 'openeo_geopyspark>=0.5.0a1.*' && \
    python3 -m pip install kazoo==2.7.0 py4j boto3==1.16.25 kubernetes==12.0.1 PyYAML==5.3.1 Jinja2==2.11.2 spark_memlogger==0.6 && \
    rm -rf /root/.cache && \
    rm -rf /var/cache/apt/*
