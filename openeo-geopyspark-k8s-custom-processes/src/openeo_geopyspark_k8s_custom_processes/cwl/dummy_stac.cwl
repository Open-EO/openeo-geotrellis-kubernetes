cwlVersion: v1.0
class: CommandLineTool
requirements:
  - class: DockerRequirement
    dockerPull: vito-docker.artifactory.vgt.vito.be/openeo-geopyspark-driver-example-stac-catalog:1.0
baseCommand: ["sh", "-c", "cp /data/* ."]
inputs: []
outputs:
  output:
    type:
      type: array
      items: File
    outputBinding:
      glob: ["*.json", "*.tif", "*.tiff"]
