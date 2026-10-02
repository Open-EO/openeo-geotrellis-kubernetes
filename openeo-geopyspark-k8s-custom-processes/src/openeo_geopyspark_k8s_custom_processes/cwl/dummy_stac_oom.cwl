#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool

# Deliberately allocates more memory than allowed
# by the ResourceRequirement (100 MiB), to trigger an OOM kill.

requirements:
  - class: DockerRequirement
    dockerPull: alpine
  - class: InitialWorkDirRequirement
    listing:
      - entryname: collection.json
        entry: |
          {
            "stac_version": "1.1.0",
            "type": "Collection",
            "id": "empty-stac-collection",
            "description": "empty-stac-collection",
            "license": "unknown",
            "extent": {
              "spatial": {"bbox": [[-180, -90, 180, 90]]},
              "temporal": {"interval": [["1900-01-01T00:00:00Z", null]]}
            },
            "links": []
          }
  - class: ResourceRequirement
    ramMin: 100
    ramMax: 100

baseCommand:
  - "sh"
  - "-c"
  - |
    # Two explicit allocations (50 MiB then 1 GiB)
    # This should trigger an OOM kill.
    chunk1=$(head -c 52428800 /dev/zero | tr "\0" "a")
    chunk2=$(head -c 1073741824 /dev/zero | tr "\0" "a")
    set -- "$@" "$chunk1" "$chunk2"
inputs: []
outputs:
  output:
    type: File
    outputBinding:
      glob: collection.json
