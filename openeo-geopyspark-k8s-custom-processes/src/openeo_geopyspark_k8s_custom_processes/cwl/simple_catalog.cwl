#!/usr/bin/env -S cwltool --strict-memory-limit --default-container=ghcr.io/open-eo/openeo-calrissian-default:1.1.0
cwlVersion: v1.2
class: CommandLineTool
requirements:
  - class: NetworkAccess
    networkAccess: true
baseCommand: [ sh, -eu, -c ]
arguments:
  - |
    base_url=https://raw.githubusercontent.com/Open-EO/openeo-python-driver/master/tests/data/simple_stac_collection
    wget "$base_url/catalog.json" "$base_url/openEO_2023-06-01Z.tif.json" "$base_url/openEO_2023-06-01Z.tif"
inputs: [ ]
outputs:
  output:
    type: Directory
    outputBinding:
      glob: .
