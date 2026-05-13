import unittest
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from phase2_brain_models import (
    Artifact,
    ArtifactKind,
    BeaconNode,
    BrainNodeType,
    BrainWritePolicy,
    Checkpoint,
    ConfidenceLevel,
    DecisionOption,
    DecisionOptionSet,
    DerivedMeasurement,
    Device,
    Equipment,
    HumanReview,
    Mission,
    ModelInterpretation,
    ObservedFact,
    Person,
    RemoteStatusArtifact,
    Route,
    Segment,
    SignalBearingMeasurement,
    SkillDefinition,
    SkillRunRecord,
    Team,
    TeamSeparationEvent,
)
from phase2_brain_store import BrainFileStore, MissingArtifactReferenceError


class Phase2BrainModelTests(unittest.TestCase):
    def test_core_brain_nodes_validate_and_serialize(self):
        nodes = [
            Mission(
                id="mission.hehuan_20260513",
                name="Hehuan team hike",
                mission_owner="person.leader",
                team_id="team.weekend_01",
                route_id="route.hehuan_loop",
            ),
            Team(
                id="team.weekend_01",
                name="Weekend group",
                leader_id="person.leader",
                member_ids=["person.leader", "person.member_02", "person.member_03"],
                remote_contact_ids=["person.remote_01"],
            ),
            Person(
                id="person.leader",
                display_name="Trip leader",
                role="leader",
                device_ids=["device.leader_watch"],
            ),
            Device(
                id="device.leader_watch",
                owner_id="person.leader",
                device_type="watch",
                platform="apple_watch",
                capabilities=["gps", "heart_rate", "battery"],
            ),
            Equipment(
                id="equipment.group_tarp",
                equipment_type="shelter",
                name="Group tarp",
                status="available",
            ),
            Route(
                id="route.hehuan_loop",
                name="Hehuan loop",
                route_type="loop",
                checkpoint_ids=["checkpoint.cp1", "checkpoint.cp2"],
                segment_ids=["segment.cp1_cp2"],
                source_artifact_refs=["artifact.route_gpx"],
            ),
            Segment(
                id="segment.cp1_cp2",
                route_id="route.hehuan_loop",
                from_checkpoint_id="checkpoint.cp1",
                to_checkpoint_id="checkpoint.cp2",
                planned_distance_m=1200.0,
                planned_duration_seconds=2400,
            ),
            Checkpoint(
                id="checkpoint.cp1",
                route_id="route.hehuan_loop",
                name="Trailhead",
                lat=24.142,
                lon=121.282,
            ),
        ]

        dumped = [node.model_dump(mode="json") for node in nodes]

        self.assertEqual(dumped[0]["type"], "Mission")
        self.assertEqual(dumped[1]["type"], "Team")
        self.assertEqual(dumped[5]["source_artifact_refs"], ["artifact.route_gpx"])

    def test_fact_measurement_interpretation_and_review_layers_are_distinct(self):
        fact = ObservedFact(
            id="fact.cp2_arrival.member_02.20260513T092211",
            subject="person.member_02",
            predicate="arrived_at_checkpoint",
            object="checkpoint.cp2",
            observed_at="2026-05-13T09:22:11+08:00",
            evidence=["artifact.sensorlog.member_02"],
            confidence=ConfidenceLevel.HIGH,
        )
        measurement = DerivedMeasurement(
            id="measurement.cp2_delay.team.20260513",
            subject="team.weekend_01",
            metric="checkpoint_arrival_delay_minutes",
            value=18,
            unit="minutes",
            derived_from=[fact.id, "route_plan.cp2_eta"],
            method="planned_eta_vs_observed_arrival",
        )
        interpretation = ModelInterpretation(
            id="interpretation.delay_reason.model_a.20260513T094000",
            subject=measurement.id,
            model="model_a",
            model_version="2026-05-13",
            claim="Delay may be related to rain, slope, and team pace compression.",
            input_refs=[measurement.id, "fact.weather_rain_segment_2"],
            generated_at="2026-05-13T09:40:00+08:00",
        )
        review = HumanReview(
            id="review.delay_reason.leader.20260513T103000",
            reviewer_id="person.leader",
            reviewed_ref=interpretation.id,
            reviewed_at="2026-05-13T10:30:00+08:00",
            decision="noted",
            notes="Leader confirmed the rain but not the pace explanation.",
        )

        self.assertEqual(fact.write_policy, BrainWritePolicy.AUTOMATIC)
        self.assertEqual(measurement.write_policy, BrainWritePolicy.AUTOMATIC)
        self.assertEqual(
            interpretation.write_policy,
            BrainWritePolicy.APPEND_ONLY_REQUIRES_REVIEW,
        )
        self.assertEqual(review.write_policy, BrainWritePolicy.HUMAN_REVIEWED)

    def test_interpretation_requires_provenance_and_append_only_policy(self):
        with self.assertRaises(ValidationError):
            ModelInterpretation(
                id="interpretation.missing_provenance",
                subject="measurement.cp2_delay",
                model="model_a",
                model_version="2026-05-13",
                claim="Delay may be weather related.",
                input_refs=[],
                generated_at="2026-05-13T09:40:00+08:00",
            )

        with self.assertRaises(ValidationError):
            ModelInterpretation(
                id="interpretation.invalid_policy",
                subject="measurement.cp2_delay",
                model="model_a",
                model_version="2026-05-13",
                claim="Delay may be weather related.",
                input_refs=["measurement.cp2_delay"],
                generated_at="2026-05-13T09:40:00+08:00",
                write_policy=BrainWritePolicy.AUTOMATIC,
            )

    def test_artifact_refs_keep_raw_payloads_out_of_graph_nodes(self):
        artifact = Artifact(
            id="artifact.sensorlog.member_02",
            artifact_kind=ArtifactKind.RAW_LOG,
            uri="artifacts/raw/member_02_sensorlog.json",
            media_type="application/json",
            sha256="a" * 64,
        )
        fact = ObservedFact(
            id="fact.battery.member_02.20260513T090000",
            subject="device.member_02_watch",
            predicate="battery_level",
            object=0.72,
            observed_at="2026-05-13T09:00:00+08:00",
            evidence=[artifact.id],
            artifact_refs=[artifact.id],
            confidence=ConfidenceLevel.HIGH,
        )

        dumped = fact.model_dump(mode="json")

        self.assertEqual(artifact.uri, "artifacts/raw/member_02_sensorlog.json")
        self.assertEqual(dumped["artifact_refs"], [artifact.id])
        self.assertNotIn("raw", dumped)

    def test_skill_status_remote_status_and_option_nodes_validate(self):
        skill = SkillDefinition(
            id="skill.team_checkin_summary.0_1_0",
            skill_id="team-checkin-summary",
            version="0.1.0",
            status="experimental",
            manifest_ref="skills/scout/team-checkin-summary.yaml",
        )
        run = SkillRunRecord(
            id="skill_run.team_checkin_summary.20260513T100000",
            skill_id=skill.skill_id,
            skill_version=skill.version,
            started_at="2026-05-13T10:00:00+08:00",
            activation_decision="allow",
            input_refs=["fact.cp2_arrival.member_02"],
            output_refs=["remote_status.20260513T100000"],
            preflight_results={"communication-state-check": "passed"},
        )
        remote_status = RemoteStatusArtifact(
            id="remote_status.20260513T100000",
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            freshness_seconds=180,
            status="delayed_but_moving",
            latest_checkpoint="checkpoint.cp2",
            next_checkpoint="checkpoint.cp3",
            safety_level="L1",
            uncertainty=ConfidenceLevel.MEDIUM,
            message="Team is delayed but still moving.",
        )
        options = DecisionOptionSet(
            id="options.retreat_or_wait.20260513T103000",
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:30:00+08:00",
            current_safety_level="L2",
            pilot_in_command="person.leader",
            options=[
                DecisionOption(
                    id="option.rest_reassess",
                    label="Rest and reassess",
                    action="rest",
                    estimated_time_minutes=20,
                    resource_cost="low",
                    reversibility="high",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            ],
        )

        self.assertEqual(run.type, BrainNodeType.SKILL_RUN_RECORD)
        self.assertEqual(remote_status.type, BrainNodeType.REMOTE_STATUS_ARTIFACT)
        self.assertEqual(options.options[0].reversibility, "high")

    def test_team_separation_and_beacon_signal_nodes_are_uncertain_by_default(self):
        separation = TeamSeparationEvent(
            id="team_separation.weekend_01.20260513T101500",
            team_id="team.weekend_01",
            detected_at="2026-05-13T10:15:00+08:00",
            member_ids=["person.member_03"],
            evidence_refs=["measurement.position_freshness.member_03"],
            severity="possible",
            reason="Member position freshness is weaker than the rest of the team.",
        )
        beacon = BeaconNode(
            id="beacon.leader_watch.20260513T102000",
            source_device_id="device.leader_watch",
            designated_at="2026-05-13T10:20:00+08:00",
            mode="mock",
            rendezvous_ref="checkpoint.cp2",
        )
        signal = SignalBearingMeasurement(
            id="signal.member_03_to_beacon.20260513T102200",
            beacon_id=beacon.id,
            observer_device_id="device.member_03_watch",
            measured_at="2026-05-13T10:22:00+08:00",
            trend="improving",
            evidence_refs=["artifact.mock_rssi_scan.member_03"],
            direction_hint="signal improved while moving northeast",
        )

        self.assertEqual(separation.severity, "possible")
        self.assertEqual(beacon.uncertainty, ConfidenceLevel.UNKNOWN)
        self.assertFalse(signal.exact_position_claimed)

        with self.assertRaises(ValidationError):
            SignalBearingMeasurement(
                id="signal.precise_position_claim",
                beacon_id=beacon.id,
                observer_device_id="device.member_03_watch",
                measured_at="2026-05-13T10:22:00+08:00",
                trend="improving",
                evidence_refs=["artifact.mock_rssi_scan.member_03"],
                exact_position_claimed=True,
            )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            ObservedFact(
                id="fact.extra",
                subject="person.member_02",
                predicate="arrived_at_checkpoint",
                object="checkpoint.cp2",
                observed_at="2026-05-13T09:22:11+08:00",
                evidence=["artifact.sensorlog.member_02"],
                confidence=ConfidenceLevel.HIGH,
                unsupported_field=True,
            )

    def test_file_store_recovers_nodes_without_live_index(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            nodes = [
                Mission(
                    id="mission.team_hike_20260513",
                    name="Team hike file brain",
                    mission_owner="person.leader",
                    team_id="team.weekend_01",
                    route_id="route.loop_01",
                ),
                Team(
                    id="team.weekend_01",
                    name="Weekend team",
                    leader_id="person.leader",
                    member_ids=["person.leader", "person.member_02", "person.member_03"],
                ),
                Person(id="person.leader", display_name="Leader", role="leader"),
                Person(id="person.member_02", display_name="Member 02"),
                Person(id="person.member_03", display_name="Member 03"),
                Device(
                    id="device.leader_watch",
                    owner_id="person.leader",
                    device_type="watch",
                    platform="apple_watch",
                    capabilities=["gps", "heart_rate"],
                ),
                Artifact(
                    id="artifact.route_gpx.loop_01",
                    artifact_kind=ArtifactKind.GPX,
                    uri="artifacts/routes/loop_01.gpx",
                    media_type="application/gpx+xml",
                ),
                Route(
                    id="route.loop_01",
                    name="Team loop",
                    route_type="loop",
                    checkpoint_ids=["checkpoint.cp1", "checkpoint.cp2"],
                    segment_ids=["segment.cp1_cp2"],
                    source_artifact_refs=["artifact.route_gpx.loop_01"],
                ),
                Checkpoint(
                    id="checkpoint.cp1",
                    route_id="route.loop_01",
                    name="Trailhead",
                    lat=24.142,
                    lon=121.282,
                ),
                Checkpoint(
                    id="checkpoint.cp2",
                    route_id="route.loop_01",
                    name="Waiting point",
                    lat=24.143,
                    lon=121.283,
                ),
                Segment(
                    id="segment.cp1_cp2",
                    route_id="route.loop_01",
                    from_checkpoint_id="checkpoint.cp1",
                    to_checkpoint_id="checkpoint.cp2",
                    planned_distance_m=900.0,
                ),
            ]

            for node in nodes:
                store.write_node(node, strict_artifact_refs=True)

            self.assertTrue((store.index_path).exists())
            self.assertTrue((store.root / "missions" / "mission.team_hike_20260513.json").exists())
            self.assertTrue((store.root / "people" / "person.member_03.json").exists())

            store.index_path.unlink()
            loaded = store.load_node("route.loop_01")
            rebuilt_index = store.rebuild_index()
            people = store.list_nodes(BrainNodeType.PERSON)

            self.assertEqual(loaded.type, BrainNodeType.ROUTE)
            self.assertIn("mission.team_hike_20260513", rebuilt_index)
            self.assertEqual([person.id for person in people], ["person.leader", "person.member_02", "person.member_03"])

    def test_file_store_rejects_missing_artifact_refs_in_strict_mode(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            route = Route(
                id="route.missing_artifact",
                name="Route with missing artifact",
                source_artifact_refs=["artifact.route_gpx.missing"],
            )
            fact = ObservedFact(
                id="fact.battery.member_02.20260513T090000",
                subject="device.member_02_watch",
                predicate="battery_level",
                object=0.72,
                observed_at="2026-05-13T09:00:00+08:00",
                evidence=["artifact.sensorlog.member_02"],
                artifact_refs=["artifact.sensorlog.member_02"],
                confidence=ConfidenceLevel.HIGH,
            )

            with self.assertRaises(MissingArtifactReferenceError):
                store.write_node(route, strict_artifact_refs=True)

            with self.assertRaises(MissingArtifactReferenceError):
                store.write_node(fact, strict_artifact_refs=True)

            store.write_node(
                Artifact(
                    id="artifact.sensorlog.member_02",
                    artifact_kind=ArtifactKind.RAW_LOG,
                    uri="artifacts/raw/member_02_sensorlog.json",
                )
            )
            path = store.write_node(fact, strict_artifact_refs=True)

            self.assertTrue(path.exists())

    def test_strict_artifact_validation_ignores_brain_node_and_external_refs(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            route = Route(
                id="route.mixed_refs",
                name="Route with mixed refs",
                source_artifact_refs=[
                    "route.source_brain_node",
                    "https://example.invalid/routes/source.gpx",
                    "skills/scout/team-checkin-summary.yaml",
                ],
            )
            fact = ObservedFact(
                id="fact.mixed_refs",
                subject="route.mixed_refs",
                predicate="source_context",
                object="available",
                observed_at="2026-05-13T09:00:00+08:00",
                evidence=["route.source_brain_node"],
                artifact_refs=[
                    "fact.source_brain_node",
                    "s3://scout-fixtures/team-replay.json",
                ],
                confidence=ConfidenceLevel.MEDIUM,
            )

            route_path = store.write_node(route, strict_artifact_refs=True)
            fact_path = store.write_node(fact, strict_artifact_refs=True)

            self.assertTrue(route_path.exists())
            self.assertTrue(fact_path.exists())

            unresolved_artifact_fact = fact.model_copy(
                update={"id": "fact.unresolved_artifact", "artifact_refs": ["artifact.missing"]}
            )
            with self.assertRaises(MissingArtifactReferenceError):
                store.write_node(unresolved_artifact_fact, strict_artifact_refs=True)


if __name__ == "__main__":
    unittest.main()
