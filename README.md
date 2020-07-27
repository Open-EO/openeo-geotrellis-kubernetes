# openeo-geotrellis-kubernetes

## Introduction

This repository contains all the required configuration and documentation to deploy the OpenEO service on Kubernetes on a DIAS cloud environment. The [CloudFerro CreoDIAS][1] Openstack was used for this setup, but should work for any Openstack environment.

The goal is to have a working OpenEO deployment, running as a Spark job, on Kubernetes, on Openstack.

## Prerequisites

  * CreoDIAS account with credits to provision Openstack resources
  * Some Kubernetes knowledge
  * A working Kubernetes cluster (see [Setup the Kubernetes environment](#setup-the-kubernetes-environment))

## Setup the Kubernetes environment

The people behind the CreoDIAS cloud have provided a [guide][2] on how to get Kubernetes installed. In the guide they make heavy use of [Kubespray][3], which is set of Terraform configuration files and Ansible playbooks. Terraform is used to provision the virtual machines, networks, ... on Openstack, while the Ansible playbooks are used to install and configure Kubernetes on those VMs.

When you have followed the guide and eventually adapted some of the Terraform variables to meet your requirements, you should have a working Kubernetes cluster:

```
[eouser@cf2-k8s-bastion-1 openeo]$ kubectl get nodes
NAME                      STATUS   ROLES    AGE   VERSION
cf2-k8s-k8s-master-nf-1   Ready    master   9d    v1.16.3
cf2-k8s-k8s-node-nf-1     Ready    <none>   9d    v1.16.3
cf2-k8s-k8s-node-nf-2     Ready    <none>   9d    v1.16.3
cf2-k8s-k8s-node-nf-3     Ready    <none>   9d    v1.16.3
cf2-k8s-k8s-node-nf-4     Ready    <none>   9d    v1.16.3
```

Only when this prerequisite is fulfilled, you can proceed to the next section.

## The Spark operator

Since Spark version 2.3.0, you can use Kubernetes as scheduler for your Spark jobs ([docs][4]). Using this functionality, you just use the regular `spark-submit` tool, with Kubernetes specific parameters. While this would work, it has some drawbacks:

  * You can't manage your Spark applications as regular Kubernetes objects and thus not use `kubectl` to manage them
  * There is no way of native cron support
  * No automatic retries
  * No built-in monitoring

To meet all these shortcomings, the GoogleCloudPlatform has developed the [spark-on-k8s-operator][5]. This operator provides a way to schedule Spark applications as native Kubernetes resources, using CRD's (Custom Resource Definitions). The operator will also manage the lifecycle of the Spark applications and provide many other features (see the Github repo for a complete feature list).

Now that we've chosen to use the operator instead of regular `spark-submit` commands, we have to get the operator installed on the cluster. The easiest way to perform the installation, is by using the [Helm chart][6]. Installation instructions on how to install Helm can be found [here][7]. It is important that you install it on the same host as where you run `kubectl` from, as Helm uses the same configuration to authenticate against your cluster.

With Helm installed, we can now install the operator. To start, we need to add the Helm chart repository to Helm:

```
helm repo add incubator http://storage.googleapis.com/kubernetes-charts-incubator
```

This makes all the incubator charts available to your Helm installation. With `helm search repo` you can see what charts are available.

You can choose in which Kubernetes namespace the spark operator will be installed. In this guide. we'll create a separate namespace for the operator and for the Spark jobs. The namespace for the Spark jobs should be created separately, as the Helm chart doesn't create it for us.

```
kubectl create namespace spark-jobs
helm install incubator/sparkoperator --generate-name --create-namespace --namespace spark-operator --set sparkJobNamespace=spark-jobs --set enableWebhook=true --set operatorVersion=v1beta2-1.1.2-2.4.5
```

Let's break down the different options passed to the `helm install` command:

| Option                  | Explanation                                                                    |
|-------------------------|--------------------------------------------------------------------------------|
| incubator/sparkoperator | Helm chart that will be installed                                              |
| --generate-name         | Generate a name for the  Helm release (Also possible to provide your own name) |
| --create-namespace      | Create the namespace if it doesn't exist yet (requires Helm 3.2+)              |
| --namespace             | The namespace where the operator will be installed in                          |
| --set sparkJobNamespace | The namespace where the Spark jobs will be deployed                            |
| --set enableWebhook     | This enables the mutating admission webhook                                    |

With the operator installed you should be able to get the following outputs:

```
helm list -n spark-operator
NAME                            NAMESPACE       REVISION        UPDATED                                         STATUS        CHART                   APP VERSION
sparkoperator-1593174963        spark-operator  1               2020-06-26 14:36:03.883398332 +0200 CEST        deployed      sparkoperator-0.7.1     v1beta2-1.1.2-2.4.5
```

and:

```
kubectl get pods -n spark-operator
NAME                                        READY   STATUS    RESTARTS   AGE
sparkoperator-1593174963-556544cb66-v5v7f   1/1     Running   0          11m
```

The Spark operator is now up and running in its own namespace.

## Deploy the OpenEO Spark job

Now that we have the Spark operator running, it's time to deploy our application on the cluster. As Kubernetes is a container orchestrator, we of course need to package our application into a container image. The necessary files to build this container image can be found in the [docker][8] directory. A prebuilt image is available at `vito-docker.artifactory.vgt.vito.be/openeo-geotrellis`.

As we are using the Spark operator, we can now define our Spark job as a Kubernetes resource, rather than a `spark-submit` script. The Kubernetes manifest for the OpenEO Spark job can be found [here][9].

Some important parts of this resource definition:

| Config               | Explanation                                                                                 |
|----------------------|---------------------------------------------------------------------------------------------|
| image                | Container image that contains the OpenEO application                                        |
| mainApplicationFile  | How the application should be started                                                       |
| sparkVersion         | The Spark version installed into the container image                                        |
| serviceAccount(*)    | The service account that has permissions to create and delete pods in the SparkJobNamespace |
| drivers.labels.name  | Important for exposing the service to the outside world later on                            |
| executor.instances   | The number of executors that should be running                                              |

\* A note about the serviceAccount: This service account name is different for every installation and should be adapted in the manifest to match yours. You can get the serviceAccount name with following command:

```
kubectl get serviceaccounts
```

and look for the one starting with `sparkoperator`.

The manifest file can now be applied to Kubernetes by using `kubectl`:

```
kubectl apply -f openeo.yaml
```

This command will create various resources on the Kubernetes cluster. With the main ones the Spark Driver and Spark Executor:

```
kubectl get pods -n spark-jobs -o wide
NAME                                     READY   STATUS    RESTARTS   AGE   IP             NODE                    NOMINATED NODE   READINESS GATES
openeo-geotrellis-1593097546965-exec-1   1/1     Running   0          22h   10.233.103.2   cf2-k8s-k8s-node-nf-2   <none>           <none>
openeo-geotrellis-driver                 1/1     Running   0          22h   10.233.80.1    cf2-k8s-k8s-node-nf-4   <none>           <none>
```

Keep in mind that the driver is started first and then the executor, so they don't show up both from the start. When they both have the `STATUS=Running`, everything works as expected. We should now be able to access the endpoint of the Spark application from within our cluster. Exposing it to the outside world is for the next section.

The previous command showed us an IP where the `openeo-geotrellis-driver` is running. It's using this IP that we can reach the application's endpoint.

To be able to reach the endpoint, we need to SSH into one of the Kubernetes cluster hosts, as the Kubernetes overlay network is not reachable from our bastion host.

From the cluster host, we can now:

```
curl 10.233.80.1:50001/openeo/1.0/collections
```

replace the IP with your own IP from the `kubectl get pods` command above. The query should give us output like the following:

```
curl 10.233.80.1:50001/openeo/1.0/collections
{"collections":[{"description":"fraction of the solar radiation absorbed by live leaves for the photosynthesis activity","extent":{"spatial":{"bbox":[[-180,-90,180,90]]},"temporal":{"interval":[["2019-01-02","2019-02-03"]]}},"id":"S2_FAPAR_CLOUDCOVER","license":"free","links":[],"stac_version":"0.9.0"},{"description":"S2_FOOBAR","extent":{"spatial":{"bbox":[[2.5,49.5,6.2,51.5]]},"temporal":{"interval":[["2019-01-01",null]]}},"id":"S2_FOOBAR","license":"free","links":[],"stac_version":"0.9.0"},{"description":"PROBAV_L3_S10_TOC_NDVI_333M_V2","extent":{"spatial":{"bbox":[[0,0,0,0]]},"temporal":{"interval":[[null,null]]}},"id":"PROBAV_L3_S10_TOC_NDVI_333M_V2","license":"proprietary","links":[],"stac_version":"0.9.0"}],"links":[]}
```

The driver also exposes the Spark UI on port 4040. The UI is exposed using a Kubernetes Service:

```
kubectl get svc --namespace spark-jobs
NAME                              TYPE           CLUSTER-IP      EXTERNAL-IP    PORT(S)             AGE
openeo-1593097546965-driver-svc   ClusterIP      None            <none>         7078/TCP,7079/TCP   22h
openeo-ui-svc                     ClusterIP      10.233.17.191   <none>         4040/TCP            22h
```

To be able to view this UI in your own web browser, you can do the following:

```
ssh -L 4040:localhost:4040 eouser@<bastion_ip>
```

and in that connected terminal you execute:

```
kubectl port-forward openeo-geotrellis-driver --namespace spark-jobs 4040
```

Now open up your browser and navigate to `localhost:4040` and you should see the Spark UI.

## Exposing the application to the outside world

Now that we have a working application endpoint, we want it to be available to others as well, as it is now only available to the Kubernetes cluster itself, not even to our bastion host.

To make this work, we're going to use [Openstack Octavia][10], a network load balancing tool, specific for Openstack. Via Kubespray, Kubernetes is configured to be able to create this load balancer on the fly.

We can create the loadbalancer by exposing our application with a `service` resource. The service manifest can be found [here][11]. Replace the `loadbalancer.openstack.org/floating-network-id` with the ID of one of your external networks.

Apply the service as follows:

```
kubectl apply -f openeo_service.yaml
```

and you should see the service coming up:

```
kubectl get svc -n spark-jobs
NAME                                         TYPE           CLUSTER-IP      EXTERNAL-IP    PORT(S)             AGE
external-openeo-geotrellis-service           LoadBalancer   10.233.7.55     <EXTERNAL_IP>  80:30807/TCP        5h29m
openeo-geotrellis-1593097546965-driver-svc   ClusterIP      None            <none>         7078/TCP,7079/TCP   22h
openeo-geotrellis-ui-svc                     ClusterIP      10.233.17.191   <none>         4040/TCP            22h
```

The `EXTERNAL-IP` should be filled in with an IP from your external network (this can take a few minutes).

If we now naviate to that `EXTERNAL-IP` from our laptop, we should get the same output as on the Kubernetes endpoint:

```
curl <EXTERNAL_IP>/openeo/1.0/collections
{"collections":[{"description":"fraction of the solar radiation absorbed by live leaves for the photosynthesis activity","extent":{"spatial":{"bbox":[[-180,-90,180,90]]},"temporal":{"interval":[["2019-01-02","2019-02-03"]]}},"id":"S2_FAPAR_CLOUDCOVER","license":"free","links":[],"stac_version":"0.9.0"},{"description":"S2_FOOBAR","extent":{"spatial":{"bbox":[[2.5,49.5,6.2,51.5]]},"temporal":{"interval":[["2019-01-01",null]]}},"id":"S2_FOOBAR","license":"free","links":[],"stac_version":"0.9.0"},{"description":"PROBAV_L3_S10_TOC_NDVI_333M_V2","extent":{"spatial":{"bbox":[[0,0,0,0]]},"temporal":{"interval":[[null,null]]}},"id":"PROBAV_L3_S10_TOC_NDVI_333M_V2","license":"proprietary","links":[],"stac_version":"0.9.0"}],"links":[]}
```

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

[1]: https://creodias.eu/
[2]: https://creodias.eu/faq-other/-/asset_publisher/SIs09LQL6Gct/content/how-to-configure-kubernetes
[3]: https://github.com/kubernetes-sigs/kubespray
[4]: https://spark.apache.org/docs/2.4.5/running-on-kubernetes.html
[5]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator
[6]: https://github.com/helm/charts/tree/master/incubator/sparkoperator
[7]: https://helm.sh/docs/intro/install
[8]: https://github.com/Open-EO/openeo-geotrellis-kubernetes/blob/master/docker
[9]: https://github.com/Open-EO/openeo-geotrellis-kubernetes/blob/master/kubernetes/openeo.yaml
[10]: https://docs.openstack.org/octavia/latest/
[11]: https://github.com/Open-EO/openeo-geotrellis-kubernetes/blob/master/kubernetes/openeo_service.yaml
[12]: https://github.com/prometheus/jmx_exporter
[13]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator/blob/master/spark-docker/conf/prometheus.yaml
[14]: https://kubernetes.io/docs/concepts/configuration/configmap/
[15]: https://github.com/GoogleCloudPlatform/spark-on-k8s-operator/blob/master/docs/quick-start-guide.md#about-the-mutating-admission-webhook
