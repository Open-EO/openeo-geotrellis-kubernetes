## Running batch jobs directly

openEO batch jobs can be started directly on a Kubernetes cluster. 
This avoids going through and requiring the full openEO web application.

A clear use case is testing, but users without an intention to operate a web service can 
also benefit from a more simple approach.

`kubectl apply -f geotrellis-batch-sparkoperator.yaml`

Stopping and removing running job:

`kubectl delete -n spark-jobs sparkapplications.sparkoperator.k8s.io job-direct-batch-test`