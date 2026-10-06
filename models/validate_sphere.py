"""Independent standalone-validator acceptance and deposited geometry export."""
from pathlib import Path
import sys
import json
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validator/src"))

from waam_validator.pipeline import run_validation
from waam_validator.config.loader import load_config
from waam_validator.trajectory.loader import load_trajectory_csv
from waam_validator.shape.deposition import build_deposited_layers
from waam_validator.shape.mesh_export import export_deposited_stl
from waam_validator.shape.polygon_utils import polygon_components
from waam_validator.shape.layer_index import layer_bounds


def main():
    job, output = (Path(p).resolve() for p in sys.argv[1:3])
    # Preserve previous acceptance reports on reruns.
    requested = output
    suffix = 2
    while output.exists() and any(output.iterdir()):
        output = requested.with_name(f"{requested.name}_{suffix}")
        suffix += 1
    result = run_validation(job, output)
    config = load_config(job / "config.yaml")
    trajectories = load_trajectory_csv(job / "trajectory.csv", config)
    deposited = build_deposited_layers(trajectories, config)
    export_deposited_stl(deposited, config, output.parent / "deposited_layers.stl")
    # The native exporter concatenates slabs, leaving shared internal faces.
    # Boolean-union the same polygons for a single watertight deliverable.
    slabs = []
    for layer, geometry in sorted(deposited.items()):
        for polygon in polygon_components(geometry):
            slab = trimesh.creation.extrude_polygon(
                polygon, config.process.layer_height_mm, engine="earcut")
            slab.apply_translation([0, 0, layer_bounds(layer, config)[0]])
            slabs.append(slab)
    solid = trimesh.boolean.union(slabs, engine="manifold")
    stl_path = output.parent / "deposited_sphere.stl"
    solid.export(stl_path)
    reloaded = trimesh.load(stl_path)
    volume = sum(p.area for p in deposited.values()) * config.process.layer_height_mm
    relative_error = abs(reloaded.volume - volume) / volume
    if not reloaded.is_watertight or relative_error > 1e-5:
        raise RuntimeError("Exported STL failed watertightness or volume verification")
    (output.parent / "artifact_verification.json").write_text(json.dumps({
        "validation_status": result.status, "validation_report": str(output),
        "stl_watertight": bool(reloaded.is_watertight),
        "stl_volume_mm3": float(reloaded.volume),
        "deposition_volume_mm3": volume, "stl_volume_relative_error": relative_error,
        "stl_faces": len(reloaded.faces),
    }, indent=2), encoding="utf-8")
    print(f"Independent validation: {result.status}", flush=True)
    print(f"Coverage={result.shape.coverage:.6%} IoU={result.shape.iou:.6%} "
          f"overfill={result.shape.overfill_ratio:.6%} collisions={len(result.collision.events)}",
          flush=True)
    if result.status != "PASS":
        print(result.failure_reasons)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
