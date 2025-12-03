#!/usr/bin/env cwl-runner
cwlVersion: v1.0
class: CommandLineTool

# This CWL uses a Docker image that was built from this Dockerfile:
# https://github.com/Open-EO/openeo-geopyspark-driver/blob/b65335184b2050ff38ce6997a0d4344c227cec9f/docker/local_batch_job/example_stac_catalog/Dockerfile
# It's a very simple image that just packages some JSON and TIFF files
# from the example STAC collection at https://github.com/Open-EO/openeo-geopyspark-driver/tree/b65335184b2050ff38ce6997a0d4344c227cec9f/docker/local_batch_job/example_stac_catalog
# This CWL just extracts these resources again and provides them as CWL output.

requirements:
  - class: DockerRequirement
    dockerPull: vito-docker.artifactory.vgt.vito.be/openeo-geopyspark-driver-example-stac-catalog:1.0

baseCommand: ["sh", "-c", "cp /data/* ."]
inputs: []
outputs:
  output:
    type: Directory
    outputBinding:
      glob: .
