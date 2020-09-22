FROM centos:7 as downloader

WORKDIR /opt

RUN yum install -y git && \
    git clone https://github.com/Open-EO/openeo-geopyspark-integrationtests.git openeo && \
    curl -O https://artifactory.vgt.vito.be/auxdata-public/openeo/geotrellis-backend-assembly-0.4.5-openeo.jar && \
    curl -O https://artifactory.vgt.vito.be/libs-snapshot-public/org/openeo/geotrellis-extensions/1.4.0-SNAPSHOT/geotrellis-extensions-1.4.0-SNAPSHOT.jar && \
    curl -O https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/0.13.0/jmx_prometheus_javaagent-0.13.0.jar

FROM gcr.io/spark-operator/spark-py:v2.4.5

LABEL maintainer="VITO Remote Sensing"

RUN printf '[global]\nindex = https://artifactory.vgt.vito.be/api/pypi/python-packages\nextra-index-url = https://artifactory.vgt.vito.be/api/pypi/python-packages/simple' > /etc/pip.conf

COPY --from=downloader /opt/openeo /tmp/openeo
COPY --from=downloader /opt/geotrellis-backend-assembly-0.4.5-openeo.jar /opt
COPY --from=downloader /opt/geotrellis-extensions-1.3.0-SNAPSHOT.jar /opt
COPY --from=downloader /opt/jmx_prometheus_javaagent-0.13.0.jar /opt

RUN python3 -m pip install -I --upgrade pip && \
    python3 -m pip install -r /tmp/openeo/requirements.txt && \
    python3 -m pip install kazoo==2.7.0 py4j && \
    rm -rf /tmp/openeo && \
    rm -rf /root/.cache && \
    rm -rf /var/cache/apt/*
