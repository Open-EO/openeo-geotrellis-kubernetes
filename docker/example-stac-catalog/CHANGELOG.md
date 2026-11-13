# example-stac-catalog image changelog

To release: add a `## <version>` section at the top, merge it, then push the git tag:
`V=image-example-stac-catalog-v$(sed -n 's/^## \([0-9][0-9.]*\)[[:space:]]*$/\1/p' CHANGELOG.md | head -n1) && git tag -a "$V" -m "$V" && git push origin "$V"`

## 1.0.0

- Initial release, taken from `openeo-geopyspark-driver`.
