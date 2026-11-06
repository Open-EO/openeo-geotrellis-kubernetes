# Small default image for Calrissian CWL steps that don't specify a DockerRequirement
# (calrissian `--default-container`), e.g. input staging steps.
ARG BASE_IMAGE=alpine:3.17.0
FROM ${BASE_IMAGE}

LABEL maintainer="VITO Remote Sensing" \
      org.opencontainers.image.title="openeo-calrissian-default" \
      org.opencontainers.image.description="Default container for Calrissian CWL steps. To suggest changes, open a pull request at https://github.com/Open-EO/openeo-geotrellis-kubernetes/tree/master/docker/calrissian-default" \
      org.opencontainers.image.source="https://github.com/Open-EO/openeo-geotrellis-kubernetes" \
      org.opencontainers.image.url="https://github.com/Open-EO/openeo-geotrellis-kubernetes/tree/master/docker/calrissian-default"

# busybox already provides `sh` and minimal applets; install the full-featured variants too.
RUN apk add --no-cache \
        bash \
        ca-certificates \
        curl \
        findutils \
        gzip \
        jq \
        tar \
        unzip \
        wget

CMD ["/bin/sh"]
