# sparkapplication chart changelog

## 0.15.0

Use `coreRequest` rather than `cores` for expressing the request size of driver and executor pods.
This is more granular than the old `cores` value and should be the preferred way. The values have
updated to have same defaults just expressed in the new way.

BREAKING CHANGE: If an override is used it is important to either migrate to the new `coreRequest`
or to set `coreRequest` to the empty string