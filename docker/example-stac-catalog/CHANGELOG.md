# example-stac-catalog image changelog

To release: add a `## <version>` section at the top, merge it, then push the git tag:
`V=image-example-stac-catalog-v$(sed -n 's/^## \([0-9][0-9.]*\)[[:space:]]*$/\1/p' CHANGELOG.md | head -n1) && git tag -a "$V" -m "$V" && git push origin "$V"`

## 2.0.0

- Breaking: move `simple_stac_merge.py` and `sub_collection_maker.py` from `/data/` to `/usr/local/bin/` (on `PATH`),
  so `/data/` only contains the example STAC collection.
  Call them by name, e.g. `baseCommand: simple_stac_merge.py` instead of `/data/simple_stac_merge.py`.
- Run as non-root user `appuser` (UID 1001, GID 0) with home and working directory `/home/appuser`.
- Pin `pystac` and `jsonschema` versions, to pass hadolint.

## 1.1.0

- Switch base image to `python:3.11-slim` and apply OS security updates (no CRITICAL Trivy findings).

## 1.0.0

- Initial release, taken from `openeo-geopyspark-driver`.
