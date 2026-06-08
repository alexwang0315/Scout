import unittest

from phase2_store_utils import append_unique, id_token, stable_dedupe


class Phase2StoreUtilsTests(unittest.TestCase):
    def test_id_token_preserves_existing_phase2_token_behavior(self):
        self.assertEqual(id_token("2026-05-13T10:00:00+08:00"), "2026-05-13T10_00_00_08_00")
        self.assertEqual(
            id_token("remote-status-json.0.1.0.2026-05-13T10:00:00+08:00"),
            "remote-status-json.0.1.0.2026-05-13T10_00_00_08_00",
        )
        self.assertEqual(id_token("__ already.safe/id  __"), "already.safe_id")

    def test_stable_dedupe_keeps_first_occurrence_order(self):
        self.assertEqual(
            stable_dedupe(["artifact.a", "artifact.b", "artifact.a", "artifact.c"]),
            ["artifact.a", "artifact.b", "artifact.c"],
        )

    def test_append_unique_returns_copy_without_readding_existing_value(self):
        refs = ["artifact.existing", "artifact.remote_status_json.20260513T100000"]

        appended = append_unique(refs, "artifact.new")
        unchanged = append_unique(refs, "artifact.remote_status_json.20260513T100000")

        self.assertEqual(
            appended,
            [
                "artifact.existing",
                "artifact.remote_status_json.20260513T100000",
                "artifact.new",
            ],
        )
        self.assertEqual(unchanged, refs)
        self.assertIsNot(unchanged, refs)


if __name__ == "__main__":
    unittest.main()
