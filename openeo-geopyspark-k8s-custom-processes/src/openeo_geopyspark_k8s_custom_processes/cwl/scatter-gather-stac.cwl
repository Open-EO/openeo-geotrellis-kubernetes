#!/usr/bin/env -S cwltool
# Run locally: cwltool --tmpdir-prefix=$HOME/tmp/ scatter-gather-stac.cwl --request_dates 2023-06-01
cwlVersion: v1.2
$graph:
  - id: sub_collection_maker
    class: CommandLineTool
    requirements:
      - class: DockerRequirement
        dockerPull: ghcr.io/open-eo/openeo-calrissian-default:1.1.0

    baseCommand: "/data/sub_collection_maker.py"
    inputs:
      request_date:
        type: string
        inputBinding: { }
    outputs:
      sub_collection_maker_out:
        type: Directory
        outputBinding:
          glob: .

  - id: scatter_node
    class: Workflow
    inputs:
      scatter_node_in1:
        type: string[]

    requirements:
      - class: ScatterFeatureRequirement

    steps:
      scatter_node_step:
        scatter: [ request_date ]
        scatterMethod: flat_crossproduct
        in:
          request_date: scatter_node_in1
        out: [ sub_collection_maker_out ]
        run: "#sub_collection_maker"

    outputs:
      - id: scatter_node_out
        outputSource: scatter_node_step/sub_collection_maker_out
        type: Directory[]

  - id: simple_stac_merge
    class: CommandLineTool
    requirements:
      - class: DockerRequirement
        dockerPull: ghcr.io/open-eo/openeo-calrissian-default:1.1.0

    baseCommand: "/data/simple_stac_merge.py"
    inputs:
      simple_stac_merge_in1:
        type: Directory[]
        inputBinding: { }
    outputs:
      simple_stac_merge_out:
        type: Directory
        outputBinding:
          glob: .

  - id: main
    class: Workflow
    inputs:
      request_dates:
        type: string[]
        default: [ "2023-06-01", "2023-06-04", "2023-06-06" ]

    requirements:
      - class: SubworkflowFeatureRequirement

    steps:
      gatherer_node_step1:
        in:
          scatter_node_in1: main/request_dates
        out: [ scatter_node_out ]
        run: "#scatter_node"
      gatherer_node_step2:
        in:
          simple_stac_merge_in1: gatherer_node_step1/scatter_node_out
        out: [ simple_stac_merge_out ]
        run: "#simple_stac_merge"
    outputs:
      - id: gatherer_node_out
        outputSource: gatherer_node_step2/simple_stac_merge_out
        type: Directory
