"""Terminal reward settings, in the units actually passed to PPO."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TerminalRewards:
    validation_bonus: float = 10.
    makespan_weight: float = 1.
    makespan_iou_threshold: float = .95
    min_mesh_iou: float = .95
    reference_seconds: float | None = None

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.validation_bonus, self.makespan_weight,
                                              self.makespan_iou_threshold, self.min_mesh_iou)):
            raise ValueError("Terminal reward settings must be finite")
        if not 0 <= self.makespan_weight < self.validation_bonus <= 1e6:
            raise ValueError("Require 0 <= makespan weight < validation bonus <= 1e6")
        if not 0 < self.makespan_iou_threshold <= 1 or not 0 < self.min_mesh_iou <= 1:
            raise ValueError("IoU thresholds must be in (0,1]")
        if self.reference_seconds is not None and (not math.isfinite(self.reference_seconds) or self.reference_seconds <= 0):
            raise ValueError("Makespan reference seconds must be finite and positive")

    def bonuses(self, *, validated, actual_iou, makespan_s, reference_seconds):
        if not validated:
            return 0., 0.
        speed = (self.makespan_weight / (1. + makespan_s/reference_seconds)
                 if actual_iou >= self.makespan_iou_threshold else 0.)
        return self.validation_bonus, speed
