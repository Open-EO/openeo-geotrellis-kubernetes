# Small default image for Calrissian CWL steps that don't specify a DockerRequirement
# (calrissian `--default-container`), e.g. input staging steps.
# Released versions are listed in CHANGELOG.md.
FROM alpine:3.24.4

LABEL maintainer="VITO Remote Sensing" \
      org.opencontainers.image.title="openeo-calrissian-default" \
      org.opencontainers.image.description="Default container for Calrissian CWL steps. Missing something? Open an issue with the use case at https://github.com/Open-EO/openeo-geotrellis-kubernetes/issues" \
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

# Run as non-root (numeric UID so `runAsNonRoot` can be verified), in the root group (GID 0)
# with group-writable home, so arbitrary UIDs (e.g. OpenShift, pod securityContext) also work.
ENV HOME=/home/calrissian
# 1001, taken from the example here: https://git.vito.be/projects/TPT/repos/mirror-calrissian/browse/Dockerfile?lines=24
RUN adduser -D -u 1001 -G root -h "${HOME}" -s /sbin/nologin -g "Default Calrissian User" calrissian && \
    chmod g+rwx "${HOME}"

USER 1001
WORKDIR ${HOME}

CMD ["/bin/sh"]
