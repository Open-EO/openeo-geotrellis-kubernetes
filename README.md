# openeo-geotrellis-kubernetes

## Introduction

This repository contains all the required configuration and documentation to deploy the OpenEO service on Kubernetes on a DIAS cloud environment. The [CloudFerro CreoDIAS][1] Openstack was used for this setup, but should work for any Openstack environment.

The goal is to have a working OpenEO deployment, running as a Spark job, on Kubernetes, on Openstack.

## Prerequisites

  * CreoDIAS account with credits to provision Openstack resources
  * Some Kubernetes knowledge
  * A working Kubernetes cluster (see [Setup the Kubernetes environment](#setup-the-kubernetes-environment))

## Setup the Kubernetes environment

To deploy a Kubernetes cluster on the CreoDIAS OpenStack, we make use of [RKE][3], Rancher Kubernetes Engine. This tool allows you to deploy a cluster that runs in containers in a fast and reliable way. Rancher also provides a [Terraform provider for RKE][16], which we use to keep all of our infrastructure provisioning within Terraform.

Steps we took to create a cluster:

1. Create an OpenStack image with Packer with all necessary dependencies like Docker, users, ...
2. Provision instances, networks, security groups, ...
3. Provision the Kubernetes cluster itself

## The Spark operator

Since Spark version 2.3.0, you can use Kubernetes as scheduler for your Spark jobs ([docs][4]). Using this functionality, you just use the regular `spark-submit` tool, with Kubernetes specific parameters. While this would work, it has some drawbacks:

  * You can't manage your Spark applications as regular Kubernetes objects and thus not use `kubectl` to manage them
  * There is no way of native cron support
  * No automatic retries
  * No built-in monitoring

To meet all these shortcomings, the GoogleCloudPlatform has developed the [spark-on-k8s-operator][5]. This operator provides a way to schedule Spark applications as native Kubernetes resources, using CRD's (Custom Resource Definitions). The operator will also manage the lifecycle of the Spark applications and provide many other features (see the Github repo for a complete feature list).

Now that we've chosen to use the operator instead of regular `spark-submit` commands, we have to get the operator installed on the cluster. The easiest way to perform the installation, is by using the [Helm chart][6]. Installation instructions on how to install Helm can be found [here][7].

With Helm installed, we can now install the operator. To start, we need to add the Helm chart repository to Helm:

```
helm repo add spark-operator https://googlecloudplatform.github.io/spark-on-k8s-operator
```

You can choose in which Kubernetes namespace the spark operator will be installed. In this guide. we'll create a separate namespace for the operator and one for the Spark jobs. The namespace for the Spark jobs should be created separately, as the Helm chart doesn't create it for us.

```
kubectl create namespace spark-jobs
helm install sparkoperator --generate-name --create-namespace --namespace spark-operator --set sparkJobNamespace=spark-jobs --set webhook.enable=true --set image.tag=v1beta2-1.3.0-3.1.1
```

Let's break down the different options passed to the `helm install` command:

| Option                  | Explanation                                                                    |
|-------------------------|--------------------------------------------------------------------------------|
| incubator/sparkoperator | Helm chart that will be installed                                              |
| --generate-name         | Generate a name for the  Helm release (Also possible to provide your own name) |
| --create-namespace      | Create the namespace if it doesn't exist yet (requires Helm 3.2+)              |
| --namespace             | The namespace where the operator will be installed in                          |
| --set sparkJobNamespace | The namespace where the Spark jobs will be deployed                            |
| --set webhook.enable    | This enables the mutating admission webhook                                    |

With the operator installed you should be able to get the following outputs:

```
helm list -n spark-operator
NAME            NAMESPACE       REVISION        UPDATED                                 STATUS          CHART                   APP VERSION
spark-operator  spark-operator  1               2022-05-13 06:17:20.165279131 +0000 UTC deployed        spark-operator-1.1.15   v1beta2-1.3.1-3.1.1
```

and:

```
kubectl get pods -n spark-operator
NAME                                        READY   STATUS    RESTARTS   AGE
sparkoperator-1593174963-556544cb66-v5v7f   1/1     Running   0          11m
```

The Spark operator is now up and running in its own namespace.

## Configuring collections
For data access, openEO requires you to register the configuration of 'collections' in a file inside the docker image. The default location is '/opt/layercatalog.json', but it can be set with an environment variable OPENEO_CATALOG_FILES.

The main format of this file follows the STAC collection metadata specification, but there's also a number of custom properties.
Documentation of these properties is rather sparse, so for now, working from existing examples is the best approach. In the best case, when working from a properly configured STAC collection, the amount of additional configuration is limited.

To update the configuration in the docker file, we would recommend rebuilding the image. Another approach might be to try and use a Kubernetes config map.

An example of a layercatalog:
https://github.com/Open-EO/openeo-geotrellis-kubernetes/blob/master/docker/creo_layercatalog.json


See: 
https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/#define-the-key-to-use-when-creating-a-configmap-from-a-file

For reference, this Python code actually works with the configuration in the layer catalog:
https://github.com/Open-EO/openeo-geopyspark-driver/blob/master/openeogeotrellis/layercatalog.py

### STAC based collection

Custom config for STAC collection. Note that 'opensearch_XX' properties are used, but the backend tries to determine automatically what to use. 

```
 "_vito": {
      "data_source": {
        "type": "file-s2",
        "opensearch_collection_id": "S2",
        "opensearch_endpoint": "https://resto.c-scale.zcu.cz",
        "provider:backend": "incd"
      }
    }
```

## Deploy the OpenEO Spark job

Now that we have the Spark operator running, it's time to deploy our application on the cluster. As Kubernetes is a container orchestrator, we of course need to package our application into a container image. The necessary files to build this container image can be found in the [docker][8] directory. A prebuilt image is available at `vito-docker.artifactory.vgt.vito.be/openeo-geotrellis-kube`.


As we are using the Spark operator, we can now define our Spark job as a Kubernetes resource, rather than a `spark-submit` script.
To have a fully functional application, we need more than a `SparkApplication` Kubernetes resource. We also need an Ingress, ServiceAccounts, RBAC, ... A [Helm chart][9] was written to help with all the parts we need. Instructions on how to use this chart, can be found in the `README.md` file.

After creating a `values.yam` file with your necessary values, you can then invoke a regular `helm install` command to deploy your instance of openEO to your Kubernetes cluster.

### Relevant config properties

The configuration of the backend is mostly done via environment variables in values.yaml. Please review these values for your backend:


| Service              | Function                                    |
|----------------------|---------------------------------------------|
| SWIFT_URL            | url of S3 API that will be used to store batch job results       |
| AWS_ACCESS_KEY_ID    | S3 Access key used to manage batch job results     |
| AWS_SECRET_ACCESS_KEY| S3 Access key secret                           |
| ZOOKEEPERNODES       | Zookeeper cluster used for persistence      |
| SIGNED_URL_SECRET    | Random secret to generate signed url's      |


## Deploy an openEO job-tracker cron job

To track the status of batch jobs, we need a job-tracker cron job. An example of such job can be found at [examples/job-tracker.yaml][17].

## Monitoring

The spark-operator also provides an easy way to monitor your Spark Applications that are submitted by the operator. In the `openeo.yaml` manifest, you can find the necessary configuration:

```
monitoring:
  exposeDriverMetrics: true
  exposeExecutorMetrics: true
  prometheus:
    jmxExporterJar: "/opt/jmx_prometheus_javaagent-0.13.0.jar"
    port: 8090
```

You can also only expose the executor's metrics for example.

This monitoring section uses a default configuration file for the [jmx_exporter][12]. The default configuration file can be found [here][13]. Of course, there is also a possibility to override this configuration. Via a Kubernetes [configMap][14], you can mount a different `prometheus.yaml` file in your driver and executor. First, a `configMap` should be created, containing the `prometheus.yaml` file:

** To make the configMaps to work, you need to enable the [mutating admission webhook][15] for the spark-operator **

```
kubectl create configmap prometheus-jmx-config --from-file=prometheus.yaml
```

This `configMap` can now be added to your pods:

```
driver:
  configMaps:
    - name: prometheus-jmx-config
      path: /opt/prometheus_config
```

The path can then be used in the monitoring configuration:

```
monitoring:
  prometheus:
    configuration: /opt/prometheus_config
```

The new metrics should now be appearing in your Prometheus instance.

## Additional services running in our cluster

| Service              | Function                                    |
|----------------------|---------------------------------------------|
| Prometheus           | Monitoring                                  |
| Grafana              | Visualize prometheus metrics                |
| Alertmanager         | Alerting                                    |
| Spark History Server | Overview of historical jobs                 |
| Zookeeper            | Keep track of batch jobs                    |
| Traefik              | Ingress                                     |
| Kubecost             | Monitoring of costs per namespace, pod, ... |
| Filebeat             | Log aggregation                             |
| RKE Pushprox         | Helper for metrics of RKE components        |
| Cinder CSI           | Dynamic OpenStack Cinder volumes            |

[1]: https://creodias.eu/
[2]: https://creodias.eu/faq-other/-/asset_publisher/SIs09LQL6Gct/content/how-to-configure-kubernetes
[3]: https://rancher.com/products/rke
[4]: https://spark.apache.org/docs/2.4.5/running-on-kubernetes.html
[5]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator
[6]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator/tree/master/charts/spark-operator-chart
[7]: https://helm.sh/docs/intro/install
[8]: https://github.com/Open-EO/openeo-geotrellis-kubernetes/blob/master/docker
[9]: https://github.com/Open-EO/openeo-geotrellis-kubernetes/tree/master/kubernetes/charts/sparkapplication
[12]: https://github.com/prometheus/jmx_exporter
[13]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator/blob/master/spark-docker/conf/prometheus.yaml
[14]: https://kubernetes.io/docs/concepts/configuration/configmap/
[15]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator/blob/master/docs/quick-start-guide.md#about-the-mutating-admission-webhook
[16]: https://registry.terraform.io/providers/rancher/rke/latest/docs
[17]: examples/job-tracker.yaml
