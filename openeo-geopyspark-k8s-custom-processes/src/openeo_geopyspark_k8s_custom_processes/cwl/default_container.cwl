#!/usr/bin/env cwl-runner
cwlVersion: v1.0
class: CommandLineTool
baseCommand:
  - sh
  - -c
  - |
    set -eu
    base_url=https://raw.githubusercontent.com/Open-EO/openeo-python-driver/master/tests/data/simple_stac_collection
    wget "$base_url/collection.json"
    wget "$base_url/openEO_2023-06-01Z.tif.json"
    wget "$base_url/openEO_2023-06-01Z.tif"
inputs: [ ]
outputs:
  output:
    type: Directory
    outputBinding:
      glob: .
