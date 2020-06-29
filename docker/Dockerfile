FROM centos:7 as downloader

WORKDIR /opt

RUN yum install -y git && \
    git clone https://github.com/Open-EO/openeo-geopyspark-integrationtests.git openeo && \
    curl -O https://artifactory.vgt.vito.be/auxdata-public/openeo/geotrellis-backend-assembly-0.4.5-openeo.jar && \
    curl -O https://artifactory.vgt.vito.be/libs-snapshot-public/org/openeo/geotrellis-extensions/1.3.0-SNAPSHOT/geotrellis-extensions-1.3.0-SNAPSHOT.jar

FROM gcr.io/spark-operator/spark-py:v2.4.5

LABEL maintainer=Vito

COPY log4j.properties /opt
COPY layercatalog.json /opt

RUN printf '[global]\nindex = https://artifactory.vgt.vito.be/api/pypi/python-packages\nextra-index-url = https://artifactory.vgt.vito.be/api/pypi/python-packages/simple' > /etc/pip.conf

COPY --from=downloader /opt/openeo /tmp/openeo
COPY --from=downloader /opt/geotrellis-backend-assembly-0.4.5-openeo.jar /opt
COPY --from=downloader /opt/geotrellis-extensions-1.3.0-SNAPSHOT.jar /opt

RUN python3 -m pip install -I --upgrade pip && \
    python3 -m pip install -r /tmp/openeo/requirements.txt && \
    python3 -m pip install kazoo==2.7.0 py4j && \
    rm -rf /tmp/openeo && \
    rm -rf /root/.cache && \
    rm -rf /var/cache/apt/*

COPY probav-mep.py /usr/local/lib/python3.7/dist-packages/openeogeotrellis/deploy/probav-mep.py
