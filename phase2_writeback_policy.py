from __future__ import annotations

from phase2_brain_models import (
    BrainNode,
    BrainWritePolicy,
    DecisionOptionSet,
    DerivedMeasurement,
    HumanReview,
    ModelInterpretation,
    ObservedFact,
)


class WritebackPolicyError(ValueError):
    pass


def automatic_write_allowed(node: BrainNode) -> bool:
    return isinstance(node, (ObservedFact, DerivedMeasurement)) and (
        node.write_policy == BrainWritePolicy.AUTOMATIC
    )


def explicit_write_allowed(node: BrainNode, *, manual_write: bool = False) -> bool:
    if isinstance(node, ModelInterpretation):
        return (
            node.write_policy == BrainWritePolicy.APPEND_ONLY_REQUIRES_REVIEW
            and len(node.input_refs) > 0
        )

    if isinstance(node, HumanReview):
        return node.write_policy == BrainWritePolicy.HUMAN_REVIEWED

    if manual_write and isinstance(node, DecisionOptionSet):
        return len(node.input_refs) > 0

    return False


def require_write_allowed(
    node: BrainNode, *, automatic: bool, manual_write: bool = False
) -> None:
    if automatic:
        if automatic_write_allowed(node):
            return
        raise WritebackPolicyError(
            f"{node.type.value} is not allowed through automatic writeback"
        )

    if explicit_write_allowed(node, manual_write=manual_write):
        return

    raise WritebackPolicyError(
        f"{node.type.value} requires an explicit non-automatic write policy"
    )
