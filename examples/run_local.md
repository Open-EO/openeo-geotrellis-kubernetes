## Geotrellis openEO on your local machine

For testing purposes, you may want to run openEO locally, this guide shows how to do this:

```
docker pull vito-docker.artifactory.vgt.vito.be/openeo-geotrellis 
docker run -it vito-docker.artifactory.vgt.vito.be/openeo-geotrellis /bin/bash
```
In the docker container:

```
export PYTHONPATH=/opt/openeo/lib64/python3.8/site-packages
export TRAVIS=1
/usr/local/spark/bin/spark-submit  --master local[1] /opt/openeo/lib64/python3.8/site-packages/openeogeotrellis/deploy/kube.py
```

TODO: integrate this in entrypoint.sh to simplify further
