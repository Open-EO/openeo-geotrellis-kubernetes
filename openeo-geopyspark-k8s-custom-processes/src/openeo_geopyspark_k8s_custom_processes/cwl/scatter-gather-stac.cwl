#!/usr/bin/env cwl-runner
# Run locally: cwltool --tmpdir-prefix=$HOME/tmp/ --force-docker-pull scatter-gather-stac.cwl --request_dates 2023-06-01
cwlVersion: v1.2
$graph:
  - id: sub_collection_maker
    class: CommandLineTool
    requirements:
      - class: DockerRequirement
        dockerPull: vito-docker.artifactory.vgt.vito.be/openeo-geopyspark-driver-example-stac-catalog:1.4

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
        dockerPull: vito-docker.artifactory.vgt.vito.be/openeo-geopyspark-driver-example-stac-catalog:1.4

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
      directory_to_file_list:
        run:
          class: ExpressionTool
          requirements:
            InlineJavascriptRequirement: { }
            LoadListingRequirement:
              loadListing: shallow_listing
          inputs:
            directory_to_file_list_in: Directory
          expression: '${return {"directory_to_file_list_out": inputs.directory_to_file_list_in.listing};}'
          outputs:
            directory_to_file_list_out: File[]
        in:
          directory_to_file_list_in: gatherer_node_step2/simple_stac_merge_out
        out: [ directory_to_file_list_out ]
    outputs:
      - id: gatherer_node_out
        outputSource: directory_to_file_list/directory_to_file_list_out
        type: File[]
