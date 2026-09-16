#!/usr/bin/env python3
"""Byte-preserving image-format fixtures; never current UI captures or PDF delivery."""
from __future__ import annotations
import ast
import base64
import copy
import html
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SYNC_PATH = Path(os.environ.get("SCOUT_GUIDE_SYNC_UNDER_TEST", ROOT / "verify_ui_sync.py"))
spec = importlib.util.spec_from_file_location("capture_format_sync", SYNC_PATH)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
tree = ast.parse((ROOT / "build.py").read_text())
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "image_html"]


class CaptureFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guide-format-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.guide = Path(self.temp.name)
        (self.guide / "assets").mkdir()
        self.slide = copy.deepcopy(next(s for s in json.loads((ROOT / "slides.json").read_text())["slides"] if s["id"] == "saved-select"))
        self.shot = copy.deepcopy(next(s for s in json.loads((ROOT / "capture-sources.json").read_text())["shots"] if s["page_id"] == "saved-select"))
        self.jpeg = (ROOT / "assets" / self.slide["image"]).read_bytes()
        self.png = (ROOT / "assets/ui-saved-select-9099-20260913.png").read_bytes()
        self.assertTrue(self.jpeg.startswith(bytes.fromhex("ffd8ff")))
        self.assertTrue(self.png.startswith(bytes.fromhex("89504e470d0a1a0a")))
        (self.guide / "assets" / self.slide["image"]).write_bytes(self.jpeg)

    def capture_errors(self):
        verifier = sync.Verifier(self.guide, self.guide, True)
        verifier.capture(self.slide, self.shot, "historical-fixture")
        return verifier.errors

    def size_errors(self, raw, name):
        path = self.guide / "assets" / name
        path.write_bytes(raw)
        verifier = sync.Verifier(self.guide, self.guide, True)
        size = verifier.image_size(path, "historical-format-fixture")
        self.assertEqual(path.read_bytes(), raw)
        return size, verifier.errors

    def test_legacy_receipt_without_mime_remains_valid(self):
        self.assertNotIn("mime_type", self.shot)
        self.assertEqual(self.capture_errors(), [])

    def test_actual_jpeg_mime_matches_original_capture(self):
        self.shot["mime_type"] = "image/jpeg"
        self.assertEqual(self.capture_errors(), [])

    def test_wrong_declared_mime_is_rejected(self):
        self.shot["mime_type"] = "image/png"
        self.assertTrue(any("MIME" in error for error in self.capture_errors()))

    def test_invalid_declared_mime_is_rejected(self):
        for value in [None, "", "image/jpg", "text/html", [], {}]:
            with self.subTest(value=value):
                self.shot["mime_type"] = value
                self.assertTrue(any("mime_type" in error for error in self.capture_errors()))

    def test_jpeg_named_png_is_rejected_without_transcoding(self):
        size, errors = self.size_errors(self.jpeg, "wrong.png")
        self.assertEqual(size, (1280, 720))
        self.assertTrue(any("extension disagrees with actual JPEG" in error for error in errors))

    def test_png_named_jpeg_is_rejected_without_transcoding(self):
        size, errors = self.size_errors(self.png, "wrong.jpg")
        self.assertEqual(size, (2880, 1368))
        self.assertTrue(any("extension disagrees with actual PNG" in error for error in errors))

    def test_jpeg_jpg_jpeg_and_uppercase_suffixes_are_valid(self):
        for suffix in [".jpg", ".jpeg", ".JPG", ".JPEG"]:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.size_errors(self.jpeg, "original" + suffix), ((1280, 720), []))

    def test_png_and_uppercase_suffixes_are_valid(self):
        for suffix in [".png", ".PNG"]:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.size_errors(self.png, "original" + suffix), ((2880, 1368), []))

    def test_png_mime_matches_original_png_bytes(self):
        path = self.guide / "assets/original.png"
        path.write_bytes(self.png)
        verifier = sync.Verifier(self.guide, self.guide, True)
        self.assertEqual(verifier.image_size(path, "fixture", "image/png"), (2880, 1368))
        self.assertEqual(verifier.errors, [])

    def test_wrong_png_mime_is_rejected(self):
        path = self.guide / "assets/original.png"
        path.write_bytes(self.png)
        verifier = sync.Verifier(self.guide, self.guide, True)
        verifier.image_size(path, "fixture", "image/jpeg")
        self.assertTrue(any("MIME" in error for error in verifier.errors))

    def test_unrecognized_signature_is_rejected(self):
        size, errors = self.size_errors(b"<html>fixture error, not screenshot</html>", "wrong.png")
        self.assertIsNone(size)
        self.assertTrue(any("file signature" in error for error in errors))

    def test_truncated_jpeg_is_rejected(self):
        size, errors = self.size_errors(self.jpeg[:-2], "truncated.jpg")
        self.assertIsNone(size)
        self.assertTrue(any("EOI" in error for error in errors))

    def test_truncated_png_header_is_rejected(self):
        size, errors = self.size_errors(self.png[:20], "truncated.png")
        self.assertIsNone(size)
        self.assertTrue(any("IHDR" in error for error in errors))

    def test_wrong_extension_rejects_complete_capture_receipt(self):
        wrong = "misnamed.png"
        (self.guide / "assets" / wrong).write_bytes(self.jpeg)
        self.slide["image"] = self.shot["asset"] = wrong
        self.assertTrue(any("extension disagrees" in error for error in self.capture_errors()))

    def test_data_uri_mime_and_original_bytes_match_valid_formats(self):
        for raw, name, mime in [(self.jpeg, "original.jpg", "image/jpeg"), (self.png, "original.png", "image/png")]:
            with self.subTest(mime=mime):
                (self.guide / "assets" / name).write_bytes(raw)
                slide = copy.deepcopy(self.slide)
                slide["image"] = name
                namespace = {"ROOT": self.guide, "base64": base64, "esc": lambda value: html.escape(str(value), quote=True), "CAPTURES": {slide["id"]: self.shot}}
                exec(compile(ast.Module(body=functions, type_ignores=[]), "image_html_fixture", "exec"), namespace)
                rendered = namespace["image_html"](slide)
                prefix = "data:" + mime + ";base64,"
                self.assertIn(prefix, rendered)
                payload = rendered.split(prefix, 1)[1].split('"', 1)[0]
                self.assertEqual(base64.b64decode(payload), raw)

    def test_wrong_mime_blocks_build_preserving_outputs(self):
        # Reuse the existing isolated all-eight-source fixture and its exact
        # pre-build output-preservation checks, never the real guide's outputs.
        dep_spec = importlib.util.spec_from_file_location("dependency_fixture_for_format", ROOT / "test_ui_dependencies.py")
        dependency = importlib.util.module_from_spec(dep_spec)
        dep_spec.loader.exec_module(dependency)
        case = dependency.CurrentDependencyTests()
        case.setUp()
        try:
            case.shot["mime_type"] = "image/png"
            case.run_blocked_build()
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main(verbosity=2)
