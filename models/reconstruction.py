"""Compare actual closed target and exported solids, beyond slice-based scores."""
import trimesh


def deposited_solid(deposited, config):
    """Same slab union for training acceptance and independent STL export."""
    from waam_validator.shape.polygon_utils import polygon_components
    from waam_validator.shape.layer_index import layer_bounds
    slabs = []
    for layer, geometry in sorted(deposited.items()):
        for polygon in polygon_components(geometry):
            slab = trimesh.creation.extrude_polygon(polygon, config.process.layer_height_mm, engine="earcut")
            slab.apply_translation([0, 0, layer_bounds(layer, config)[0]])
            slabs.append(slab)
    if not slabs:
        raise ValueError("No deposited geometry")
    return trimesh.boolean.union(slabs, engine="manifold")


def compare_solids(target, deposited):
    if not target.is_volume or not deposited.is_volume:
        raise ValueError("Solid comparison requires closed, consistently oriented positive-volume meshes")
    intersection = trimesh.boolean.intersection([target, deposited], engine="manifold")
    overlap = 0. if intersection is None or intersection.is_empty else float(abs(intersection.volume))
    target_volume, deposited_volume = float(target.volume), float(deposited.volume)
    overlap = min(max(0., overlap), target_volume, deposited_volume)
    union = target_volume + deposited_volume - overlap
    difference = max(0., target_volume + deposited_volume - 2*overlap)
    return {"method": "manifold_boolean_volume", "target_volume_mm3": target_volume,
            "deposited_volume_mm3": deposited_volume, "intersection_volume_mm3": overlap,
            "iou": overlap/union, "similarity_percent": 100*overlap/union,
            "coverage": overlap/target_volume, "overfill": (deposited_volume-overlap)/target_volume,
            "symmetric_difference_mm3": difference,
            "symmetric_difference_relative": difference/target_volume,
            "equal_within_volume_tolerance": difference/target_volume <= 1e-6,
            "equality_volume_tolerance": 1e-6}
