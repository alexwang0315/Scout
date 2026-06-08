import unittest
from pathlib import Path

from communication_provider import FixtureCommunicationProvider
from communication_tool import FixtureCommunicationTool
from environment_provider import FixtureEnvironmentProvider
from mission_models import CommunicationState, EnvironmentState, ResourceState
from provider_context import load_fixture_provider_bundle, mission_context_from_providers, provider_evidence
from resource_provider import FixtureResourceProvider


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_DIR = ROOT / "tests" / "fixtures" / "mission_context"


class ProviderContextTests(unittest.TestCase):
    def test_fixture_provider_bundle_builds_normalized_mission_context(self):
        bundle = load_fixture_provider_bundle(CONTEXT_DIR / "normal.json")

        context = mission_context_from_providers(bundle)

        self.assertEqual(context.resource_state.device_battery, 0.82)
        self.assertEqual(context.environment_state.visibility, "good")
        self.assertEqual(context.communication_state.best_delivery_confidence, 0.75)
        self.assertEqual(context.route_context["current_segment_id"], "seg_01")

    def test_provider_evidence_is_json_ready(self):
        bundle = load_fixture_provider_bundle(CONTEXT_DIR / "no_signal_high_risk_zone.json")
        context = mission_context_from_providers(bundle)

        evidence = provider_evidence(context)

        self.assertEqual(evidence["resource_state"]["device_battery"], 0.48)
        self.assertEqual(evidence["environment_state"]["weather_risk"], 0.35)
        self.assertEqual(evidence["communication_state"]["capabilities"][0]["channel"], "cellular")
        self.assertEqual(evidence["route_context"]["control_zone_id"], "zone_steep_descent")

    def test_fixture_providers_keep_go_no_go_decoupled_from_fixture_shape(self):
        communication_state = CommunicationState.model_validate(
            {
                "capabilities": [
                    {
                        "channel": "bluetooth",
                        "available": True,
                        "supports_inbound": True,
                        "supports_nearby_pull": True,
                        "estimated_delivery_confidence": 0.45,
                    }
                ]
            }
        )
        bundle = load_fixture_provider_bundle(CONTEXT_DIR / "normal.json")
        custom_bundle = type(bundle)(
            resource_provider=FixtureResourceProvider(
                ResourceState(device_battery=0.9, estimated_human_energy=0.8)
            ),
            environment_provider=FixtureEnvironmentProvider(EnvironmentState(weather_risk=0.2)),
            communication_provider=FixtureCommunicationProvider(tool=FixtureCommunicationTool(communication_state)),
            route_context={"current_segment_id": "seg_02"},
        )

        context = mission_context_from_providers(custom_bundle)

        self.assertEqual(context.resource_state.device_battery, 0.9)
        self.assertEqual(context.communication_state.best_delivery_confidence, 0.45)
        self.assertEqual(context.route_context["current_segment_id"], "seg_02")


if __name__ == "__main__":
    unittest.main()
