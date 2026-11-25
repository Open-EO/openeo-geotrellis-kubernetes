#!/usr/bin/env -S cwltool --preserve-environment AWS_ACCESS_KEY_ID --preserve-environment AWS_SECRET_ACCESS_KEY --preserve-environment AWS_ENDPOINT_URL_S3 --preserve-environment AWS_REGION
cwlVersion: v1.2
class: CommandLineTool
requirements:
  - class: DockerRequirement
    dockerPull: ghcr.io/open-eo/example-stac-catalog:1.1.0
  - class: NetworkAccess
    networkAccess: true
  - class: InitialWorkDirRequirement
    listing:
      - entryname: boto3_test.py
        entry: |
          """Download a file from S3 with boto3 and write a hardcoded STAC catalog next to it."""

          import json
          import os
          from pathlib import Path

          import boto3
          from botocore.config import Config

          # On the cluster: credentials/endpoint are injected in the pod, region must match (e.g. "eodata").
          region_name = os.environ.get("AWS_REGION", "eodata")
          print(f"{region_name=} endpoint={os.environ['AWS_ENDPOINT_URL_S3']}")
          eodata_path = "/eodata/Sentinel-2/MSI/L2A_N0500/2020/03/22/S2B_MSIL2A_20200322T074609_N0500_R135_T36NYH_20230612T214223.SAFE/GRANULE/L2A_T36NYH_A015891_20200322T075811/IMG_DATA/R20m/T36NYH_20200322T074609_SCL_20m.jp2"

          bucket, key = eodata_path.lstrip("/").split("/", 1)

          s3 = boto3.client(
              "s3",
              region_name=region_name,
              config=Config(
                  s3={"addressing_style": "path"},
                  request_checksum_calculation="when_required",
                  response_checksum_validation="when_required",
              ),
          )

          filename = os.path.basename(key)
          output_dir = Path(__file__).resolve().parent
          s3.download_file(bucket, key, str(output_dir / filename))

          item_id = "T36NYH_20200322T074609_SCL_20m"
          root = {"rel": "root", "href": "./catalog.json", "type": "application/json"}
          parent = {**root, "rel": "parent"}
          x0, y0, x1, y1 = 34.7974981913524, 1.71875060835491, 35.78573229612569, 2.712829405612157
          item = {
              "type": "Feature",
              "stac_version": "1.1.0",
              "stac_extensions": ["https://stac-extensions.github.io/projection/v2.0.0/schema.json"],
              "id": item_id,
              "geometry": {"type": "Polygon", "coordinates": [[[x1, y0], [x1, y1], [x0, y1], [x0, y0], [x1, y0]]]},
              "bbox": [x0, y0, x1, y1],
              "properties": {
                  "proj:code": "EPSG:32636",
                  "proj:shape": [5490, 5490],
                  "proj:transform": [20, 0, 699960, 0, -20, 300000],
                  "datetime": "2020-03-22T07:46:09Z",
              },
              "links": [root, parent],
              "assets": {"SCL": {"href": filename, "type": "image/jp2", "roles": ["data"]}},
          }
          catalog = {
              "type": "Catalog",
              "id": "boto3-test",
              "stac_version": "1.1.0",
              "description": "catalog",
              "links": [root, {"rel": "item", "href": f"./{item_id}.json", "type": "application/geo+json"}],
          }
          (output_dir / f"{item_id}.json").write_text(json.dumps(item, indent=2))
          (output_dir / "catalog.json").write_text(json.dumps(catalog, indent=2))
          print(f"STAC catalog written to {output_dir / 'catalog.json'}")
baseCommand: [ "sh", "-eux", "-c", "pip install --quiet --no-cache-dir --root-user-action=ignore --target /tmp/pydeps boto3; PYTHONPATH=/tmp/pydeps python boto3_test.py; rm boto3_test.py" ]
inputs: [ ]
outputs:
  output:
    type: Directory
    outputBinding:
      glob: .
