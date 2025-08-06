# sparkapplication chart changelog

## 1.0.3

feature: allow specifying PriorityClassName for driver.

## 1.0.1

fix: Make sure the Values of rbac.clusterRoleName and rbac.clusterRoleBindingName are used when specified.

## 1.0.0

Go to version 1 in order to start following semantic versioning conventions.

- !Breaking change: default cluster role binding also includes a namespace.
This change is needed to allow deploying the chart multiple times on a single Kubernetes cluster.
It avoids conflicts in cluster-role-binding names. It also avoids overriding the cluster-role and the cluster-role-binding names
but the defaults should also work now (but the change in default means it is a breaking change)

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
