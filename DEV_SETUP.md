# Install microk8s

See https://microk8s.io/docs/getting-started
 
```
sudo snap install microk8s --classic --channel=1.32
sudo usermod -a -G microk8s $USER
mkdir -p ~/.kube
chmod 0700 ~/.kube
su - $USER
```

# Install Spark Operator

```
microk8s helm repo add spark-operator https://kubeflow.github.io/spark-operator
microk8s helm repo update
microk8s helm install spark-operator/spark-operator --generate-name --create-namespace --namespace spark-operator --set sparkJobNamespace=spark-jobs --set webhook.enable=true
```

