from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from pretrip_models import CandidateReviewState, PreTripPackage
except ImportError:  # pragma: no cover - keeps this slice loadable while models move.
    CandidateReviewState = None  # type: ignore[assignment]
    PreTripPackage = None  # type: ignore[assignment]


ACCEPTED = "accepted"
REJECTED = "rejected"
NEEDS_REVIEW = "needs_review"
NOTED = "noted"
CORRECTED = "corrected"

DEFAULT_CANDIDATE_COLLECTIONS = (
    "checkpoint_candidates",
    "segment_candidates",
    "retreat_route_candidates",
    "route_guide_timing_candidates",
)


def resolve_pretrip_reviewed_package(
    package: Any,
    reviews: list[Any] | tuple[Any, ...],
) -> Any:
    """Return a reviewed PreTripPackage view without mutating the source package."""

    view = _copy_package(package)
    candidates_by_id = _index_candidates(view)

    for review in reviews:
        decision = _review_decision(review)
        if decision == NOTED:
            continue

        candidate_id = _review_candidate_id(review)
        if not candidate_id:
            raise ValueError(f"review is missing candidate id: {review!r}")
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"review references unknown PreTrip candidate: {candidate_id}")

        if decision == ACCEPTED:
            _set_candidate_value(candidate, "review_state", _state_value(ACCEPTED))
        elif decision == REJECTED:
            _set_candidate_value(candidate, "review_state", _state_value(REJECTED))
        elif decision == CORRECTED:
            _apply_correction(candidate, _review_correction_payload(review))
            _set_candidate_value(candidate, "review_state", _corrected_review_state(review))
        else:
            raise ValueError(f"unsupported PreTrip review decision: {decision}")

    return _validate_like_source(view, package)


def resolve_reviewed_pretrip_package(package: Any, reviews: list[Any] | tuple[Any, ...]) -> Any:
    return resolve_pretrip_reviewed_package(package, reviews)


def apply_pretrip_reviews(package: Any, reviews: list[Any] | tuple[Any, ...]) -> Any:
    return resolve_pretrip_reviewed_package(package, reviews)


def _copy_package(package: Any) -> Any:
    if hasattr(package, "model_copy"):
        return package.model_copy(deep=True)
    return deepcopy(package)


def _validate_like_source(view: Any, source: Any) -> Any:
    if PreTripPackage is not None and isinstance(source, dict):
        return PreTripPackage.model_validate(view)
    if hasattr(source, "__class__") and hasattr(source.__class__, "model_validate"):
        return source.__class__.model_validate(source.__class__.model_validate(view).model_dump(mode="json"))
    return view


def _index_candidates(package: Any) -> dict[str, Any]:
    by_id: dict[str, Any] = {}
    for collection_name in DEFAULT_CANDIDATE_COLLECTIONS:
        for candidate in _candidate_collection(package, collection_name):
            candidate_id = _candidate_id(candidate)
            if not candidate_id:
                continue
            if candidate_id in by_id:
                raise ValueError(f"duplicate PreTrip candidate id: {candidate_id}")
            by_id[candidate_id] = candidate
    return by_id


def _candidate_collection(package: Any, collection_name: str) -> list[Any]:
    if isinstance(package, dict):
        return package.get(collection_name, [])
    return getattr(package, collection_name, [])


def _candidate_id(candidate: Any) -> str | None:
    return _value(candidate, "candidate_id")


def _review_candidate_id(review: Any) -> str | None:
    for key in (
        "reviewed_ref",
        "candidate_id",
        "target_candidate_id",
        "review_target_id",
        "target_id",
        "item_id",
    ):
        value = _value(review, key)
        if value:
            return str(value)
    return None


def _review_decision(review: Any) -> str:
    for key in ("decision", "review_decision", "action", "status"):
        value = _value(review, key)
        if value:
            return _normal_string(value)
    raise ValueError(f"review is missing decision: {review!r}")


def _review_correction_payload(review: Any) -> dict[str, Any]:
    for key in ("correction_payload", "correction", "patch", "payload", "updates"):
        value = _value(review, key)
        if value is None:
            continue
        if hasattr(value, "payload"):
            return dict(value.payload)
        if not isinstance(value, dict):
            raise ValueError(f"correction payload must be a mapping: {review!r}")
        if "payload" in value and isinstance(value["payload"], dict):
            return dict(value["payload"])
        return dict(value)
    return {}


def _corrected_review_state(review: Any) -> Any:
    for key in (
        "review_state",
        "result_review_state",
        "resolved_review_state",
        "candidate_review_state",
    ):
        value = _value(review, key)
        if value:
            state = _normal_string(value)
            if state not in {ACCEPTED, NEEDS_REVIEW}:
                raise ValueError(
                    "corrected review_state must be accepted or needs_review: "
                    f"{value}"
                )
            return _state_value(state)
    return _state_value(ACCEPTED)


def _apply_correction(candidate: Any, payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if key == "candidate_id":
            raise ValueError("correction payload cannot change candidate_id")
        _set_candidate_value(candidate, key, value)


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _set_candidate_value(candidate: Any, key: str, value: Any) -> None:
    if isinstance(candidate, dict):
        candidate[key] = value
        return
    setattr(candidate, key, value)


def _state_value(state: str) -> Any:
    if CandidateReviewState is None:
        return state
    return CandidateReviewState(state)


def _normal_string(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()
