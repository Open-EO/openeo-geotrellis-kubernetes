import sys
import shutil
from pathlib import Path

containing_folder = Path(__file__).parent

p = containing_folder.parent / "src/openeo_geopyspark_k8s_custom_processes"
assert p.exists()
sys.path.append(str(p))
import ogk_utils


def test_get_files_from_stac_catalog_path():
    stac_root = containing_folder / "example_stac_catalog/collection.json"
    ret = ogk_utils.get_files_from_stac_catalog(stac_root)
    print(ret)
    assert len(ret) == 6


def test_get_files_from_stac_catalog_url():
    stac_root = "https://raw.githubusercontent.com/Open-EO/openeo-geopyspark-driver/refs/heads/master/docker/local_batch_job/example_stac_catalog/collection.json"
    ret = ogk_utils.get_files_from_stac_catalog(stac_root)

    print(ret)
    assert len(ret) == 6


def test_get_assets_from_stac_catalog():
    stac_root = containing_folder / "example_stac_catalog/collection.json"
    ret = ogk_utils.get_assets_from_stac_catalog(stac_root)
    print(ret)
    assert len(ret.values()) == 3


def test_stac_save_result():
    tmp_dir = Path("tmp_stac_save_result")
    if tmp_dir.exists():
        # make sure the folder is empty
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()

    stac_root = "https://raw.githubusercontent.com/Open-EO/openeo-geopyspark-driver/refs/heads/master/docker/local_batch_job/example_stac_catalog/collection.json"
    sr = ogk_utils.StacSaveResult(stac_root)
    ret = sr.write_assets(tmp_dir)
    print(ret)
    assert len(ret) == 3
