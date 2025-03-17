# sparkapplication chart changelog

## 0.17.2
- Allow advanced TLS configuration for spark-ui
- Add support for different scheduler refs
- restart sparkapp on configmap change

## 0.16.0

Add `global.extraEnv`, `driver.extraEnv` and `executor.extraEnv` to allow setting environment variables
using the [envvar-v1-core spec](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.24/#envvar-v1-core).
This allows to set environment variables that are not yet known at deployment time.

## 0.15.0

Use `coreRequest` rather than `cores` for expressing the request size of driver and executor pods.
This is more granular than the old `cores` value and should be the preferred way. The values have
updated to have same defaults just expressed in the new way.

BREAKING CHANGE: If an override is used it is important to either migrate to the new `coreRequest`
or to set `coreRequest` to the empty string