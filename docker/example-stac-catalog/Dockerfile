# Simple Dockerfile to package this example STAC collection as a Docker image.
# For example to be used in a dummy CWL workflow that produces a STAC collection.

FROM python:3.11-slim

# Apply OS security updates.
# Remove wheel and setuptools (which vendors wheel) from base image: not needed, CVE-2026-24049
RUN apt-get update \
 && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/* \
 && pip uninstall -y wheel setuptools \
 && pip install --no-cache-dir pystac jsonschema
RUN mkdir /data
COPY collection.json openEO*.tif openEO*.json *.py /data/
