# Simple Dockerfile to package this example STAC collection as a Docker image.
# For example to be used in a dummy CWL workflow that produces a STAC collection.

FROM python:3.11-slim

# Apply OS security updates.
# Remove wheel and setuptools (which vendors wheel) from base image: not needed, CVE-2026-24049
RUN apt-get update \
 && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/* \
 && pip uninstall -y wheel setuptools \
 && pip install --no-cache-dir pystac==1.16.1 jsonschema==4.26.0
COPY --chmod=755 *.py /usr/local/bin/
COPY collection.json openEO*.tif openEO*.json /data/

# Run as non-root (numeric UID so `runAsNonRoot` can be verified), in the root group (GID 0)
# with group-writable home, so arbitrary UIDs (e.g. OpenShift, pod securityContext) also work.
ENV HOME=/home/appuser
RUN useradd -u 1001 -g 0 -m -d "${HOME}" -s /usr/sbin/nologin -c "appuser" appuser && \
    chmod g+rwx "${HOME}"

USER 1001
WORKDIR ${HOME}
