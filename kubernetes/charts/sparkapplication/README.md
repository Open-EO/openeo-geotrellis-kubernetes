# Helm Chart for Spark applications using the Spark Operator

This is the Helm chart to create the openEO webapp driver Sparkpplication, using the CRD provided by the [Kubernetes Operator for Apache Spark](https://github.com/kubeflow/spark-operator).

### Prerequisites

As the Spark Operator requires Kubernetes 1.13 or above, this chart needs the same. It also requires an instance of the Spark Operator in your cluster. You can deploy one with the provided [Helm Chart](https://github.com/kubeflow/spark-operator/tree/master/charts/spark-operator-chart)

### Installing the Chart

The chart can be found in our public Helm repository. Add the repository:

```bash
$ helm repo add <repo_name> https://artifactory.vgt.vito.be/artifactory/helm-charts
```

Install the chart with:

```bash
$ helm install <repo_name>/sparkapplication --generate-name --namespace <namespace>
```

There are 4 required parameters to be set:
  * image
  * imageVersion
  * mainApplicationFile
  * rbac.serviceAccountDriver

### Sample values

Following is an example `values.yaml` file:

```yaml
---
image: vito-docker.artifactory.vgt.vito.be/openeo-geotrellis-kube
imageVersion: latest
driver:
  env:
    KUBE: "true"
    KUBE_OPENEO_API_PORT: "50001"
    PYTHONPATH: $PYTHONPATH:/opt/openeo/lib/python3.8/site-packages/
    SPARK_LOCAL_IP: "127.0.0.1"
  ports:
    - name: webapp
      containerPort: 50001
      protocol: TCP
executor:
  env:
    PYTHONPATH: $PYTHONPATH:/opt/openeo/lib/python3.8/site-packages/
ha:
  enabled: false
jarDependencies:
  - local:///opt/geotrellis-extensions-static.jar
mainApplicationFile: local:///opt/openeo/lib64/python3.8/site-packages/openeogeotrellis/deploy/kube.py
rbac:
  create: true
  role:
    rules:
      - apiGroups:
          - ""
        resources:
          - pods
        verbs:
          - create
          - delete
          - deletecollection
          - get
          - list
          - patch
          - watch
      - apiGroups:
          - ""
        resources:
          - configmaps
        verbs:
          - create
          - delete
          - deletecollection
          - list
      - apiGroups:
          - ""
        resources:
          - persistentvolumeclaims
        verbs:
          - create
          - delete
          - deletecollection
          - list
      - apiGroups:
          - ""
        resources:
          - services
        verbs:
          - deletecollection
          - list
      - apiGroups:
          - sparkoperator.k8s.io
        resources:
          - sparkapplications
        verbs:
          - create
          - delete
          - get
          - list
  serviceAccountDriver: openeo
restartPolicy:
  type: Always
service:
  enabled: true
  port: 50001
serviceAccount: openeo
sparkConf:
  spark.appMasterEnv.DRIVER_IMPLEMENTATION_PACKAGE: openeogeotrellis
  spark.executorEnv.DRIVER_IMPLEMENTATION_PACKAGE: openeogeotrellis
sparkVersion: 3.2.0
type: Java
fileDependencies:
  - local:///opt/layercatalog.json
```

This should give a working webapp driver that can be accessed on port 50001 via port-forwarding. The chart has the possibility to create an Ingress as well.

### LayerCatalog

#### Stage via initContainer

If you want to stage a LayerCatalog using an initContainer you must specify it in the Values by updating layerCatalog.viaInitContainer
- Set enabled to true
- Provide image repository and tag

That way the container image is ran as an initContainer. It will get an environment variable `TARGET_DIR` which will point to `.Values.layerCatalog.viaInitContainer.targetDir` which defaults to `/opt/layercatalogs` so you must make sure that:
- The init container puts the files in `$TARGET_DIR`
- [You configure the geopyspark-driver to use the proper layercatalog JSON files](https://github.com/Open-EO/openeo-geopyspark-driver/blob/6793adc498bdd1433191a83248cda8ec3e3f34f8/openeogeotrellis/config/config.py#L88)
- Container image tags are immutable or you must make sure to AlwaysPull and not have any caching in image sources


### HA mode

As the `SparkApplication` CRD doesn't provide the ability to run in HA, the chart was developed to create multiple separate SparkApplications when HA mode is activated. The `Service` has a `Selector` that matches both drivers and thus an `Ingress` can be created to expose a HA Spark driver.
