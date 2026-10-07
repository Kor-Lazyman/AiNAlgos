"""Generate explicit geometry-planned trajectories, then independently validate STL reconstruction."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import hashlib
import math
import yaml

from models import __version__
from planning.geometry import build_plan, compile_trajectory
from train import discover_targets, create_run_directory, write_csv

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT/"output"/"planned")
    parser.add_argument("--min-mesh-iou", type=float, default=.95)
    parser.add_argument("--layer-height", type=float, help="Explicit process override in the copied job, in mm")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if not 0 < args.min_mesh_iou <= 1:
        parser.error("--min-mesh-iou must be in (0,1]")
    if args.layer_height is not None and (not math.isfinite(args.layer_height) or args.layer_height <= 0):
        parser.error("--layer-height must be finite and positive")
    args.job_dir = args.job_dir.expanduser().resolve()
    sources = discover_targets(args.job_dir)
    output = create_run_directory(args.output)
    reports = []
    for number, source in enumerate(sources, 1):
        directory = output/"result"/f"{number:03d}_{source.stem}"
        job = directory/"job"
        job.mkdir(parents=True)
        shutil.copy2(source, job/"target.stl")
        shutil.copy2(args.job_dir/"config.yaml", job/"config.yaml")
        if args.layer_height is not None:
            config_data = yaml.safe_load((job/"config.yaml").read_text(encoding="utf-8"))
            config_data["process"]["layer_height_mm"] = args.layer_height
            (job/"config.yaml").write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
        (directory/"provenance.json").write_text(json.dumps({
            "target_source": str(source), "target_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_config_sha256": hashlib.sha256((args.job_dir/"config.yaml").read_bytes()).hexdigest(),
            "process_overrides": {} if args.layer_height is None else {"layer_height_mm": args.layer_height},
            "generator": "geometry_planner_not_ppo", "required_actual_mesh_iou": args.min_mesh_iou,
        }, indent=2), encoding="utf-8")
        print(f"Planning {source.name}", flush=True)
        try:
            config, sections = build_plan(job)
            write_csv(job/"trajectory.csv", compile_trajectory(config, sections))
            write_csv(directory/"trajectory_robot_modes.csv", compile_trajectory(config, sections, True))
            (directory/"plan.json").write_text(json.dumps({"generator": "geometry_planner_not_ppo",
                "sections": [{"index": s.index, "robot": s.robot+1, "parameters": s.parameters,
                              "predicted_iou": s.predicted_iou, "paths": [p.tolist() for p in s.paths]}
                             for s in sections]}, indent=2), encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT/"validate.py"), str(job), str(directory/"validation"),
                                     "--min-mesh-iou", str(args.min_mesh_iou)])
            reports.append({"target": source.name, "status": "PASS" if result.returncode == 0 else "FAIL",
                            "directory": str(directory)})
        except Exception as error:
            reports.append({"target": source.name, "status": "FAIL", "error": str(error), "directory": str(directory)})
            (directory/"planning_failure.json").write_text(json.dumps(reports[-1], indent=2), encoding="utf-8")
    summary = {"version": __version__, "generator": "geometry_planner_not_ppo", "targets": reports,
               "status": "PASS" if all(r["status"]=="PASS" for r in reports) else "FAIL"}
    (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"]=="PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
