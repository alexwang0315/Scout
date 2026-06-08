from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_models import BrainNodeType, DerivedMeasurement
from phase2_brain_store import BrainFileStore
from pretrip_brain_seed import export_chilai_pretrip_brain_seed
from pretrip_brain_seed_store import (
    write_chilai_pretrip_seed_to_brain_store,
    write_pretrip_seed_to_brain_store,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_write_pretrip_seed_bundle_to_brain_file_store_with_strict_artifact_refs():
    seed = export_chilai_pretrip_brain_seed(
        FIXTURE_ROOT,
        reviewed=True,
        mission_id="mission.chilai_nanhua_day1.0.1.0",
        package_uri="outputs/pretrip_package.reviewed.json",
        review_log_uri="reviews/human_reviews.json",
    )

    with TemporaryDirectory() as tmpdir:
        store = BrainFileStore(tmpdir)
        result = write_pretrip_seed_to_brain_store(store, seed, strict_artifact_refs=True)

        assert result.observed_fact_count == 0
        assert result.counts_by_node_type == {
            "Artifact": 13,
            "DerivedMeasurement": 31,
            "HumanReview": 245,
            "ModelInterpretation": 6,
        }
        assert len(result.node_ids) == 295
        assert len(result.paths) == 295
        assert result.node_ids[0] == "artifact.gpx.chilai_nanhua_day1"
        assert "artifact.photo.g11_hiking" in result.node_ids[:13]
        assert "artifact.pretrip_package.chilai_nanhua_day1" in result.node_ids[:13]

        route_distance = store.load_node("measurement.pretrip_route_distance_m.chilai_nanhua_day1")
        assert isinstance(route_distance, DerivedMeasurement)
        assert route_distance.artifact_refs == [
            "artifact.gpx.chilai_nanhua_day1",
            "artifact.pretrip_package.chilai_nanhua_day1",
        ]
        assert all(
            store.load_node(node_id).type != BrainNodeType.OBSERVED_FACT
            for node_id in result.node_ids
        )
        interpretation = store.load_node(
            "interpretation.pretrip_output.plan_validation_candidates.chilai_nanhua_day1.v0"
        )
        assert interpretation.type == BrainNodeType.MODEL_INTERPRETATION
        assert interpretation.write_policy == "append_only_requires_review"
        assert (
            Path(tmpdir)
            / "measurements"
            / "measurement.pretrip_route_distance_m.chilai_nanhua_day1.json"
        ).exists()


def test_write_chilai_seed_convenience_exports_and_writes_reviewed_fixture():
    with TemporaryDirectory() as tmpdir:
        result = write_chilai_pretrip_seed_to_brain_store(
            BrainFileStore(tmpdir),
            FIXTURE_ROOT,
            reviewed=True,
            mission_id="mission.chilai_nanhua_day1.0.1.0",
            package_uri="outputs/pretrip_package.reviewed.json",
            review_log_uri="reviews/human_reviews.json",
            strict_artifact_refs=True,
        )

        payload = result.model_dump()

        assert payload["observed_fact_count"] == 0
        assert payload["counts_by_node_type"]["Artifact"] == 13
        assert payload["counts_by_node_type"]["ModelInterpretation"] == 6
        assert payload["paths"]["artifact.pretrip_package.chilai_nanhua_day1"].endswith(
            "artifacts/artifact.pretrip_package.chilai_nanhua_day1.json"
        )
