import unittest
import trimesh

from models.reconstruction import compare_solids


class ReconstructionTests(unittest.TestCase):
    def test_identical_solid_with_different_triangulation(self):
        target = trimesh.creation.box(extents=[2, 2, 2])
        result = compare_solids(target, target.subdivide())
        self.assertAlmostEqual(result["iou"], 1.)
        self.assertTrue(result["equal_within_volume_tolerance"])

    def test_equal_volume_does_not_mean_equal_shape(self):
        target = trimesh.creation.box(extents=[2, 2, 2])
        shifted = target.copy()
        shifted.apply_translation([1, 0, 0])
        result = compare_solids(target, shifted)
        self.assertAlmostEqual(result["iou"], 1/3)
        self.assertAlmostEqual(result["coverage"], .5)
        self.assertAlmostEqual(result["overfill"], .5)
        self.assertFalse(result["equal_within_volume_tolerance"])

    def test_disjoint_solids(self):
        target = trimesh.creation.box()
        other = target.copy()
        other.apply_translation([3, 0, 0])
        self.assertEqual(compare_solids(target, other)["iou"], 0.)
