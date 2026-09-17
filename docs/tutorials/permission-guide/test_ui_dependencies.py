#!/usr/bin/env python3
"""Source and build-gate regression fixtures, never current UI/PDF qualification."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SYNC_PATH = Path(os.environ.get("SCOUT_GUIDE_SYNC_UNDER_TEST", ROOT / "verify_ui_sync.py"))
SPEC = importlib.util.spec_from_file_location("guide_dependency_sync_under_test", SYNC_PATH)
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)

MAP_UI = {
    "docs/admin/scout-dashboard-v0.1.html",
    "docs/admin/phase4-pretrip-planning.html",
    "docs/admin/scout-maplibre-evidence.js",
}
PERMISSION_UI = {
    "docs/admin/scout-planned-route.js",
    "docs/admin/scout-planned-map-review.js",
    "docs/admin/scout-planned-review-ui.js",
    "docs/admin/scout-exploration-workflow.js",
    "docs/admin/scout-recorded-workflow.js",
}
ALL_UI = MAP_UI | PERMISSION_UI


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CurrentDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="permission-guide-dependency-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.historical = self.base / "historical"
        self.current = self.base / "actual-current-source"
        self.guide = self.historical / "docs/tutorials/permission-guide"
        (self.guide / "assets").mkdir(parents=True)
        for root in (self.historical, self.current):
            for name in ALL_UI:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                # Deterministic fixture text only; no source file or browser is modified.
                path.write_text("fixture source version 1: " + name + "\n")
        slide = next(s for s in json.loads((ROOT / "slides.json").read_text())["slides"] if s["id"] == "saved-select")
        shot = next(s for s in json.loads((ROOT / "capture-sources.json").read_text())["shots"] if s["page_id"] == "saved-select")
        self.slide, self.shot = copy.deepcopy(slide), copy.deepcopy(shot)
        # Reuse a preserved image only to exercise the verifier's geometry contract.
        # This isolated unit fixture is not a new screenshot or capture receipt.
        self.slide["capture_context"] = self.shot["source_context"] = "fixture-current"
        shutil.copy2(ROOT / "assets" / slide["image"], self.guide / "assets" / slide["image"])
        self.captures = {
            "schema_version": 2,
            "ui_source_hashes": {name: sha(self.historical / name) for name in ALL_UI},
            "current_ui_source": {
                "source_id": "fixture-current",
                "checkout_root": str(self.current),
                "ui_source_hashes": {name: sha(self.current / name) for name in ALL_UI},
            },
            "shots": [self.shot],
        }
        self.write_inputs()

    def write_inputs(self):
        (self.guide / "slides.json").write_text(json.dumps({"slides": [self.slide]}))
        (self.guide / "capture-sources.json").write_text(json.dumps(self.captures))

    def report(self, *, captures_only=True):
        self.write_inputs()
        return SYNC.Verifier(self.guide, self.historical, captures_only).run()

    def assert_dependency_failure(self, report):
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(
            any("current_ui_source" in error for error in report["errors"]),
            report,
        )

    def test_all_eight_current_sources_and_existing_capture_contract_pass(self):
        report = self.report()
        self.assertEqual(report["errors"], [], report)
        self.assertEqual(report["current_ui_status"], "live_source_hashes_match")

    def test_a_changed_required_source_makes_the_capture_stale(self):
        for name in sorted(ALL_UI):
            with self.subTest(source=name):
                path = self.current / name
                before = path.read_bytes()
                path.write_bytes(before + b"changed current UI\n")
                report = self.report()
                self.assert_dependency_failure(report)
                self.assertTrue(any(name in error and "differs" in error for error in report["errors"]), report)
                path.write_bytes(before)

    def test_omitting_any_of_the_eight_current_hashes_is_rejected(self):
        hashes = self.captures["current_ui_source"]["ui_source_hashes"]
        for name in sorted(ALL_UI):
            with self.subTest(source=name):
                digest = hashes.pop(name)
                self.assert_dependency_failure(self.report())
                hashes[name] = digest

    def test_historical_hashes_cannot_cover_omitted_changed_permission_modules(self):
        hashes = self.captures["current_ui_source"]["ui_source_hashes"]
        for name in sorted(PERMISSION_UI):
            with self.subTest(source=name):
                digest = hashes.pop(name)
                path = self.current / name
                before = path.read_bytes()
                path.write_bytes(before + b"current renderer changed\n")
                self.assertEqual(sha(self.historical / name), self.captures["ui_source_hashes"][name])
                self.assert_dependency_failure(self.report())
                path.write_bytes(before)
                hashes[name] = digest

    def test_original_three_hash_manifest_cannot_label_new_current_capture_fresh(self):
        hashes = self.captures["current_ui_source"]["ui_source_hashes"]
        self.captures["current_ui_source"]["ui_source_hashes"] = {name: hashes[name] for name in MAP_UI}
        self.assert_dependency_failure(self.report())

    def test_explicit_current_root_is_checked_independently_of_guide_location(self):
        target = self.current / "docs/admin/scout-recorded-workflow.js"
        target.write_text("actual live renderer differs from historical TASK\n")
        report = self.report()
        self.assert_dependency_failure(report)
        self.assertTrue(any("scout-recorded-workflow.js" in error and "differs" in error for error in report["errors"]), report)

    def test_missing_current_checkout_does_not_fall_back_to_historical_sources(self):
        self.captures["current_ui_source"]["checkout_root"] = str(self.base / "unavailable-current-source")
        before = {name: os.environ.pop(name, None) for name in ("SCOUT_PERMISSION_GUIDE_MAC_HOST", "SCOUT_PERMISSION_GUIDE_MAC_IDENTITY")}
        try:
            self.assert_dependency_failure(self.report())
        finally:
            for name, value in before.items():
                if value is not None:
                    os.environ[name] = value

    def test_all_source_hashes_do_not_substitute_for_a_missing_capture(self):
        self.captures["shots"] = []
        report = self.report()
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("no capture-sources.json shot" in error for error in report["errors"]), report)

    def test_all_source_hashes_do_not_substitute_for_correct_step_geometry(self):
        self.slide["markers"][0]["target"]["x"] += 20
        report = self.report()
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("box differs from captured DOM geometry" in error for error in report["errors"]), report)

    def test_full_mode_also_reports_stale_current_dependencies(self):
        (self.current / "docs/admin/scout-planned-map-review.js").write_text("changed current renderer\n")
        self.assert_dependency_failure(self.report(captures_only=False))

    def run_blocked_build(self):
        shutil.copy2(ROOT / "build.py", self.guide / "build.py")
        shutil.copy2(SYNC_PATH, self.guide / "verify_ui_sync.py")
        names = ("index.html", "presenter-notes.md", "build-manifest.json", "permission-guide.pdf")
        for name in names:
            (self.guide / name).write_bytes(("preserved existing fixture output: " + name).encode())
        before = {name: sha(self.guide / name) for name in names}
        self.write_inputs()
        result = subprocess.run([sys.executable, str(self.guide / "build.py")], text=True, capture_output=True, check=False, timeout=30)
        self.assertNotEqual(result.returncode, 0, result)
        self.assertIn("Recapture changed UI:", result.stderr)
        self.assertEqual(before, {name: sha(self.guide / name) for name in names})

    def test_stale_dependency_blocks_build_before_touching_html_or_pdf(self):
        (self.current / "docs/admin/scout-exploration-workflow.js").write_text("changed current source\n")
        self.run_blocked_build()

    def test_omitted_dependency_blocks_build_before_touching_html_or_pdf(self):
        del self.captures["current_ui_source"]["ui_source_hashes"]["docs/admin/scout-planned-review-ui.js"]
        self.run_blocked_build()

    def test_missing_capture_blocks_build_before_touching_html_or_pdf(self):
        self.captures["shots"] = []
        self.run_blocked_build()


if __name__ == "__main__":
    unittest.main(verbosity=2)
