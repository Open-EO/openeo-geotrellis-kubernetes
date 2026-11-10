# openeo-calrissian-default image changelog

To release: add a `## <version>` section at the top, merge it, then push the git tag:
`V=image-openeo-calrissian-default-v$(sed -n 's/^## \([0-9][0-9.]*\)[[:space:]]*$/\1/p' CHANGELOG.md | head -n1) && git tag -a "$V" -m "$V" && git push origin "$V"`

Missing something? Open an issue with the use case: https://github.com/Open-EO/openeo-geotrellis-kubernetes/issues

## 1.1.0

- Run as non-root user `calrissian` (UID 1001, GID 0, same as the Calrissian image) with home and working directory `/home/calrissian`.

## 1.0.0

- Initial release, based on `alpine:3.24.4`.
- Includes `bash`, `ca-certificates`, `curl`, `findutils`, `gzip`, `jq`, `tar`, `unzip` and `wget`.
