"""Independent standalone-validator acceptance and deposited geometry export."""
from pathlib import Path
import sys
import json
import trimesh
import argparse
import hashlib
from models.reconstruction import compare_solids, deposited_solid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "validator/src"))

from waam_validator.pipeline import run_validation
from waam_validator.config.loader import load_config
from waam_validator.trajectory.loader import load_trajectory_csv
from waam_validator.shape.deposition import build_deposited_layers
from waam_validator.shape.target import load_target_mesh
from waam_validator.shape.mesh_export import export_deposited_stl
from waam_validator.errors import WaamValidatorError


def main(*, stl_name="deposited.stl"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--min-mesh-iou", type=float, default=.95)
    args = parser.parse_args()
    if not 0 < args.min_mesh_iou <= 1:
        parser.error("--min-mesh-iou must be in (0,1]")
    job, output = args.job.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve previous acceptance reports on reruns.
    requested = output
    suffix = 2
    while output.exists() and any(output.iterdir()):
        output = requested.with_name(f"{requested.name}_{suffix}")
        suffix += 1
    # Invalidate any previous acceptance before starting a rerun. An unexpected
    # geometry/export error must never leave an old PASS as the current result.
    (output.parent / "artifact_verification.json").write_text(json.dumps({
        "validation_status": "FAIL", "validation_report": str(output),
        "stl_generated": False, "error": "Verification has not completed",
    }, indent=2), encoding="utf-8")
    try:
        result = run_validation(job, output)
    except WaamValidatorError as exc:
        (output.parent / "artifact_verification.json").write_text(json.dumps({
            "validation_status": "FAIL", "validation_report": str(output),
            "stl_generated": False, "error_code": exc.code, "error": str(exc),
        }, indent=2), encoding="utf-8")
        print(f"Independent validation: FAIL ({exc.code}): {exc}", flush=True)
        raise SystemExit(1)
    config = load_config(job / "config.yaml")
    trajectories = load_trajectory_csv(job / "trajectory.csv", config)
    deposited = build_deposited_layers(trajectories, config)
    export_deposited_stl(deposited, config, output.parent / "deposited_layers.stl")
    # The native exporter concatenates slabs, leaving shared internal faces.
    # Boolean-union the same polygons for a single watertight deliverable.
    if not any(p.area > 0 for p in deposited.values()):
        (output.parent / "artifact_verification.json").write_text(json.dumps({
            "validation_status": "FAIL", "validation_report": str(output),
            "stl_generated": False, "error": "No deposited geometry",
        }, indent=2), encoding="utf-8")
        print(f"Independent validation: {result.status}; no deposited geometry to export", flush=True)
        raise SystemExit(1)
    solid = deposited_solid(deposited, config)
    stl_path = output.parent / stl_name
    solid.export(stl_path)
    reloaded = trimesh.load(stl_path)
    volume = sum(p.area for p in deposited.values()) * config.process.layer_height_mm
    relative_error = abs(reloaded.volume - volume) / volume
    if not reloaded.is_watertight or relative_error > 1e-5:
        raise RuntimeError("Exported STL failed watertightness or volume verification")
    comparison = compare_solids(load_target_mesh(job / "target.stl", config), reloaded)
    comparison["required_iou"] = args.min_mesh_iou
    comparison["passed"] = comparison["iou"] >= args.min_mesh_iou
    (output.parent / "mesh_comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    final_status = "PASS" if result.status == "PASS" and comparison["passed"] else "FAIL"
    (output.parent / "artifact_verification.json").write_text(json.dumps({
        "validation_status": final_status, "nominal_validation_status": result.status, "validation_report": str(output),
        "mesh_comparison": comparison,
        "input_sha256": {name: hashlib.sha256((job/name).read_bytes()).hexdigest() for name in ("target.stl", "config.yaml", "trajectory.csv")},
        "stl_generated": True,
        "stl_watertight": bool(reloaded.is_watertight),
        "stl_volume_mm3": float(reloaded.volume),
        "deposition_volume_mm3": volume, "stl_volume_relative_error": relative_error,
        "stl_faces": len(reloaded.faces),
    }, indent=2), encoding="utf-8")
    print(f"Independent validation: {final_status}; actual solid IoU={comparison['iou']:.6%}", flush=True)
    print(f"Coverage={result.shape.coverage:.6%} IoU={result.shape.iou:.6%} "
          f"overfill={result.shape.overfill_ratio:.6%} collisions={len(result.collision.events)}",
          flush=True)
    if final_status != "PASS":
        print(result.failure_reasons)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
