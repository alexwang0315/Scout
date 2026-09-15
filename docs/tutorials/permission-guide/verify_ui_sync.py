#!/usr/bin/env python3
"""Check Permission screenshots, numbered targets, UI freshness, and deliverables.

Read-only and dependency-free. This command never updates evidence or hashes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
from typing import Any
from urllib.parse import parse_qs, urlparse

GUIDE = Path(__file__).resolve().parent
BOX_KEYS = ("x", "y", "width", "height")
PIXEL_TOLERANCE = 0.01
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PRIMARY_UI = "docs/admin/scout-dashboard-v0.1.html"
CURRENT_MAP_UI = {PRIMARY_UI, "docs/admin/phase4-pretrip-planning.html", "docs/admin/scout-maplibre-evidence.js"}
# These modules render the Permission chapters in the current Dashboard.
# Historical TASK hashes cannot establish their freshness in the live Mac UI.
CURRENT_PERMISSION_UI = {
    "docs/admin/scout-planned-route.js",
    "docs/admin/scout-planned-map-review.js",
    "docs/admin/scout-planned-review-ui.js",
    "docs/admin/scout-exploration-workflow.js",
    "docs/admin/scout-recorded-workflow.js",
}
CURRENT_GUIDE_UI = CURRENT_MAP_UI | CURRENT_PERMISSION_UI


def number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def page_id(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())) or (type(value) is int and value >= 0)


def jpeg_size(data: bytes) -> tuple[int, int]:
    """Read JPEG frame dimensions without decoding, transcoding, or cropping."""
    if not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG is missing its final EOI marker; recapture the complete original image")
    position = 2  # SOI was already identified from the file signature.
    while position < len(data):
        if data[position] != 0xFF:
            raise ValueError("invalid JPEG marker before the frame header")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in (0xD9, 0xDA):
            break  # A valid screenshot has its SOF before scan data or EOI.
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue  # Standalone marker: no segment-length field.
        if marker in (0x00, 0xD8) or position + 2 > len(data):
            raise ValueError("invalid or truncated JPEG marker")
        length = struct.unpack(">H", data[position:position + 2])[0]
        if length < 2 or position + length > len(data):
            raise ValueError("invalid or truncated JPEG segment length")
        segment = data[position + 2:position + length]
        position += length
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if len(segment) < 6 or segment[5] == 0 or len(segment) != 6 + 3 * segment[5]:
                raise ValueError("invalid JPEG SOF component table")
            height, width = struct.unpack(">HH", segment[1:5])
            if width == 0 or height == 0:
                raise ValueError("JPEG SOF dimensions must be positive")
            return width, height
    raise ValueError("JPEG is missing a SOF frame header before scan data")


class Verifier:
    def __init__(self, guide: Path, repo: Path, captures_only: bool) -> None:
        self.guide, self.repo = guide.resolve(), repo.resolve()
        self.captures_only = captures_only
        self.errors: list[str] = []
        self.slide_count = self.shot_count = 0
        self.current_ui_status = "not_declared"

    def require(self, condition: bool, where: str, message: str) -> bool:
        if not condition:
            self.errors.append(f"{where}: {message}")
        return condition

    def load(self, name: str) -> dict[str, Any]:
        try:
            value = json.loads((self.guide / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.errors.append(f"{name}: cannot read JSON ({exc})")
            return {}
        return value if self.require(isinstance(value, dict), name, "expected a JSON object") else {}

    def relative_file(self, base: Path, name: Any, where: str, filename_only: bool = False) -> Path | None:
        if not self.require(isinstance(name, str) and bool(name.strip()), where, "expected a relative file path"):
            return None
        relative = Path(name)
        if not self.require(not relative.is_absolute() and ".." not in relative.parts, where, "path must stay within its source directory"):
            return None
        if filename_only and not self.require(relative.name == name, where, "use the filename inside assets/, without directory components"):
            return None
        path = (base / relative).resolve()
        if not self.require(path.is_relative_to(base.resolve()), where, "resolved file escapes its source directory"):
            return None
        return path if self.require(path.is_file(), where, f"missing file: {path}") else None

    def check_hash(self, path: Path | None, expected: Any, where: str, action: str) -> None:
        if not self.require(isinstance(expected, str) and SHA256.fullmatch(expected) is not None, where, "expected a lowercase SHA-256 digest") or path is None:
            return
        try:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()
        except OSError as exc:
            self.errors.append(f"{where}: cannot hash file ({exc})")
            return
        self.require(digest == expected, where, f"SHA-256 mismatch; {action}")

    def image_size(self, path: Path | None, where: str, declared_mime: Any = None) -> tuple[int, int] | None:
        if path is None:
            return None
        try:
            data = path.read_bytes()
            if data.startswith(b"\x89PNG\r\n\x1a\n"):
                image_format, extensions = "PNG", {".png"}
                if len(data) < 24 or data[8:16] != b"\x00\x00\x00\rIHDR":
                    raise ValueError("PNG is missing a complete IHDR header")
                size = struct.unpack(">II", data[16:24])
            elif data.startswith(b"\xff\xd8"):
                image_format, extensions = "JPEG", {".jpg", ".jpeg"}
                size = jpeg_size(data)
            else:
                raise ValueError("expected original PNG or JPEG bytes, identified by the file signature")
            self.require(path.suffix.lower() in extensions, where, f"file extension disagrees with actual {image_format} format; retain the original screenshot bytes and correct filename")
            if declared_mime is not None:
                actual_mime = "image/png" if image_format == "PNG" else "image/jpeg"
                self.require(declared_mime == actual_mime, where + ".mime_type", f"declared MIME disagrees with actual {image_format} bytes; retain the original bytes and correct the receipt")
            return size if self.require(all(value > 0 for value in size), where, f"{image_format} dimensions must be positive") else None
        except (OSError, ValueError) as exc:
            self.errors.append(f"{where}: cannot read image format/dimensions ({exc})")
            return None

    def box(self, value: Any, size: tuple[int, int], where: str) -> bool:
        if not self.require(isinstance(value, dict) and all(number(value.get(k)) for k in BOX_KEYS), where, "expected finite x, y, width, height in screenshot pixels"):
            return False
        x, y, width, height = (value[k] for k in BOX_KEYS)
        return self.require(x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= size[0] + PIXEL_TOLERANCE and y + height <= size[1] + PIXEL_TOLERANCE, where, "target box is outside the screenshot or has no area; recapture the visible target")

    def numbered(self, entries: Any, count: int, where: str) -> dict[int, dict[str, Any]]:
        if not self.require(isinstance(entries, list), where, "expected an array with one entry per step"):
            return {}
        result: dict[int, dict[str, Any]] = {}
        for index, entry in enumerate(entries):
            at = f"{where}[{index}]"
            if not self.require(isinstance(entry, dict), at, "expected an object"):
                continue
            step = entry.get("step")
            if not self.require(type(step) is int and 1 <= step <= count, at, f"step must be an integer from 1 to {count}"):
                continue
            if self.require(step not in result, at, f"duplicate step {step}"):
                result[step] = entry
        self.require(set(result) == set(range(1, count + 1)), where, f"need exactly one entry for every step 1–{count}")
        return result

    def capture(self, slide: dict[str, Any], shot: dict[str, Any], where: str) -> None:
        steps = slide.get("steps")
        if not self.require(isinstance(steps, list) and len(steps) > 0, where + ".steps", "every page, including the cover, needs visible numbered steps"):
            return
        self.require(all(isinstance(step, dict) and isinstance(step.get("title"), str) and bool(step["title"].strip()) for step in steps), where + ".steps", "each step needs a non-empty title")
        image = slide.get("image")
        path = self.relative_file(self.guide / "assets", image, where + ".image", filename_only=True)
        self.require(shot.get("asset") == image, where + ".capture.asset", "capture asset must equal the slide image")
        self.check_hash(path, shot.get("sha256"), where + ".capture.sha256", "use the original captured PNG/JPEG bytes and their capture receipt")
        # Historical receipts did not declare MIME. When the capture tool returns
        # it, preserve it and verify it instead of assuming the requested format.
        if "mime_type" in shot:
            self.require(shot["mime_type"] in ("image/png", "image/jpeg"), where + ".capture.mime_type", "record the original PNG/JPEG MIME type returned by the capture tool")
        size = self.image_size(path, where + ".image", shot.get("mime_type"))
        self.require(all(type(shot.get(key)) is int and shot[key] > 0 for key in ("width", "height")), where + ".capture", "width and height must be positive integers from the image header")
        if size:
            self.require((shot.get("width"), shot.get("height")) == size, where + ".capture", f"capture dimensions must match image {size[0]}×{size[1]}")
        self.require(isinstance(shot.get("project"), str) and bool(shot["project"].strip()), where + ".capture.project", "record the exact workspace/project ID")
        url = shot.get("url")
        try:
            parsed = urlparse(url) if isinstance(url, str) else None
            valid_url = parsed is not None and parsed.scheme in ("http", "https") and bool(parsed.netloc)
            self.require(valid_url, where + ".capture.url", "record the actual HTTP(S) UI URL")
            projects = parse_qs(parsed.query).get("projectId", []) if valid_url else []
            self.require(not projects or projects == [shot.get("project")], where + ".capture.url", "URL projectId differs from the captured project")
        except ValueError:
            self.errors.append(f"{where}.capture.url: invalid URL")
        try:
            stamp = datetime.fromisoformat(str(shot.get("captured_at", "")).replace("Z", "+00:00"))
            self.require(stamp.tzinfo is not None, where + ".capture.captured_at", "include the capture timezone")
        except ValueError:
            self.errors.append(f"{where}.capture.captured_at: expected an ISO-8601 capture timestamp")
        ratio = shot.get("pixel_ratio", 1)
        if "pixel_ratio" in shot:
            valid_ratio = number(ratio) and ratio > 0
            self.require(valid_ratio, where + ".capture.pixel_ratio", "pixel_ratio must be a positive finite number from the screenshot/viewport ratio")
            viewport = shot.get("viewport") if isinstance(shot.get("viewport"), dict) else {}
            self.require(all(number(viewport.get(k)) and viewport[k] > 0 for k in ("width", "height")), where + ".capture.viewport", "scaled screenshots require their original CSS viewport")
            if valid_ratio and all(number(shot.get(k)) and number(viewport.get(k)) and viewport[k] > 0 for k in ("width", "height")):
                self.require(all(abs(shot[k] - viewport[k] * ratio) <= PIXEL_TOLERANCE for k in ("width", "height")), where + ".capture.pixel_ratio", "image dimensions must equal the CSS viewport times pixel_ratio")
        markers = self.numbered(slide.get("markers"), len(steps), where + ".markers")
        targets = self.numbered(shot.get("targets"), len(steps), where + ".capture.targets")
        for step, marker in markers.items():
            at = f"{where}.step[{step}]"
            target = targets.get(step, {})
            locator = marker.get("locator")
            self.require(isinstance(locator, str) and bool(locator.strip()), at + ".locator", "record the DOM locator used for this target")
            self.require(locator == target.get("locator"), at + ".locator", "marker locator differs from captured DOM target")
            if "pixel_ratio" in shot:
                css_box = target.get("css_box") if isinstance(target.get("css_box"), dict) else {}
                image_box = target.get("box") if isinstance(target.get("box"), dict) else {}
                self.require(all(number(css_box.get(k)) and number(image_box.get(k)) for k in BOX_KEYS), at + ".css_box", "keep the original DOM CSS rectangle for scaled captures")
                if number(ratio) and all(number(css_box.get(k)) and number(image_box.get(k)) for k in BOX_KEYS):
                    self.require(all(abs(css_box[k] * ratio - image_box[k]) <= PIXEL_TOLERANCE for k in BOX_KEYS), at + ".css_box", "image target must equal original CSS coordinates times pixel_ratio")
            if size:
                self.require(number(marker.get("x")) and number(marker.get("y")) and 0 <= marker["x"] <= size[0] and 0 <= marker["y"] <= size[1], at, "marker position is outside the screenshot or not finite")
                marker_ok = self.box(marker.get("target"), size, at + ".target")
                capture_ok = self.box(target.get("box"), size, at + ".captured_box")
                if marker_ok and capture_ok:
                    self.require(all(abs(marker["target"][k] - target["box"][k]) <= PIXEL_TOLERANCE for k in BOX_KEYS), at + ".target", "box differs from captured DOM geometry; update marker from the new capture, not by guessing")

    def sources(self, captures: dict[str, Any]) -> None:
        sources = captures.get("ui_source_hashes")
        if not self.require(isinstance(sources, dict) and len(sources) > 0, "capture-sources.json.ui_source_hashes", "record the UI source files used for the captures"):
            return
        self.require(PRIMARY_UI in sources, "capture-sources.json.ui_source_hashes", f"must include {PRIMARY_UI}; do not remove a changed UI file to pass")
        for name, digest in sources.items():
            where = f"ui_source_hashes[{name}]"
            path = self.relative_file(self.repo, name, where)
            self.check_hash(path, digest, where, "UI teaching is stale; inspect the changed UI, recapture affected pages, and rebuild HTML/PDF")

    def current_sources(self, captures: dict[str, Any]) -> None:
        """Verify the live Mac checkout independently of historical TASK hashes."""
        current = captures.get("current_ui_source")
        if current is None:
            return
        self.current_ui_status = "unverified"
        start_errors = len(self.errors)
        if not self.require(isinstance(current, dict), "current_ui_source", "expected a source-context object"):
            return
        hashes, root_value = current.get("ui_source_hashes"), current.get("checkout_root")
        if not self.require(isinstance(hashes, dict) and CURRENT_GUIDE_UI.issubset(hashes), "current_ui_source.ui_source_hashes", "capture all eight current Dashboard / Phase4 / MapLibre / Permission module source hashes; historical TASK hashes cannot substitute or cover an omitted dependency"):
            return
        if not self.require(isinstance(root_value, str) and Path(root_value).is_absolute(), "current_ui_source.checkout_root", "record the actual absolute Mac checkout path"):
            return
        for name, digest in hashes.items():
            safe = isinstance(name, str) and name.startswith("docs/admin/") and ".." not in Path(name).parts and Path(name).suffix in (".html", ".js", ".css")
            self.require(safe, "current_ui_source", "current-source paths must be UI files within docs/admin/")
            self.require(isinstance(digest, str) and SHA256.fullmatch(digest) is not None, f"current_ui_source[{name}]", "record a SHA-256 from the current capture; pending or invented hashes cannot pass")
        if len(self.errors) != start_errors:
            return
        root = Path(root_value)
        observed: dict[str, str] = {}
        if root.is_dir():
            for name in hashes:
                path = self.relative_file(root, name, f"current_ui_source[{name}]")
                if path:
                    try:
                        observed[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                    except OSError as exc:
                        self.errors.append(f"current_ui_source[{name}]: cannot read current UI ({exc})")
        else:
            host = os.environ.get("SCOUT_PERMISSION_GUIDE_MAC_HOST", "")
            identity = os.environ.get("SCOUT_PERMISSION_GUIDE_MAC_IDENTITY", "")
            valid_host = bool(host) and not host.startswith("-") and re.fullmatch(r"[A-Za-z0-9_.@:-]+", host) is not None
            if not self.require(valid_host and Path(identity).is_absolute() and Path(identity).is_file(), "current_ui_source", "Mac checkout is not local; supply SCOUT_PERMISSION_GUIDE_MAC_HOST and SCOUT_PERMISSION_GUIDE_MAC_IDENTITY for a live read-only SSH hash check"):
                return
            request = json.dumps({"root": root_value, "paths": sorted(hashes)})
            source = "from pathlib import Path\nimport hashlib,json\nrequest=json.loads(" + repr(request) + ")\nroot=Path(request['root']).resolve()\nresult={}\nfor name in request['paths']:\n p=(root/name).resolve()\n if not p.is_relative_to(root) or not p.is_file(): raise ValueError('current UI source missing or outside checkout')\n result[name]=hashlib.sha256(p.read_bytes()).hexdigest()\nprint(json.dumps(result))\n"
            command = ["ssh", "-i", identity, "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, "python3", "-"]
            try:
                result = subprocess.run(command, input=source, capture_output=True, text=True, timeout=20, check=False)
                if result.returncode != 0:
                    self.errors.append(f"current_ui_source: live Mac SSH hash check failed (exit {result.returncode}); reconnect the source checkout before building")
                    return
                observed = json.loads(result.stdout)
                if not isinstance(observed, dict):
                    raise ValueError("source hash response is not an object")
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                self.errors.append(f"current_ui_source: current checkout could not be verified ({type(exc).__name__}); no historical fallback is allowed")
                return
        for name, digest in hashes.items():
            self.require(observed.get(name) == digest, f"current_ui_source[{name}]", "live Mac source differs from this capture; recheck current UI and recapture affected pages")
        if len(self.errors) == start_errors:
            self.current_ui_status = "live_source_hashes_match"

    def generated(self, slides: list[Any]) -> None:
        manifest = self.load("build-manifest.json")
        delivery = self.load("delivery.json")
        for name, document in (("build-manifest.json", manifest), ("delivery.json", delivery)):
            self.require(type(document.get("slide_count")) is int and document["slide_count"] == len(slides), name + ".slide_count", f"expected {len(slides)}; regenerate the guide and delivery receipt")
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        for name in ("slides.json", "index.html", "presenter-notes.md", "capture-sources.json", "build.py", "verify-browser.js"):
            record = files.get(name) if isinstance(files.get(name), dict) else {}
            path = self.relative_file(self.guide, name, "build-manifest.json.files." + name)
            self.check_hash(path, record.get("sha256"), "build-manifest.json.files." + name, "run build.py and recheck the rebuilt guide")
            if path and "bytes" in record:
                self.require(type(record["bytes"]) is int and record["bytes"] == path.stat().st_size, "build-manifest.json.files." + name, "byte count differs; rebuild the manifest")
        html = self.relative_file(self.guide, "index.html", "delivery.json.html_sha256")
        self.check_hash(html, delivery.get("html_sha256"), "delivery.json.html_sha256", "validate the final HTML and refresh the delivery receipt")
        pdf = delivery.get("pdf") if isinstance(delivery.get("pdf"), dict) else {}
        path = self.relative_file(self.guide, "permission-guide.pdf", "delivery.json.pdf")
        self.check_hash(path, pdf.get("sha256"), "delivery.json.pdf.sha256", "render and validate the PDF from the final HTML, then refresh the delivery receipt")
        self.require(type(pdf.get("pages")) is int and pdf["pages"] == len(slides), "delivery.json.pdf.pages", f"expected {len(slides)} PDF pages; rerun PDF page validation")
        if path and "bytes" in pdf:
            self.require(type(pdf["bytes"]) is int and pdf["bytes"] == path.stat().st_size, "delivery.json.pdf.bytes", "PDF byte count differs; validate the final PDF")

    def run(self) -> dict[str, Any]:
        deck, captures = self.load("slides.json"), self.load("capture-sources.json")
        self.require(type(captures.get("schema_version")) is int and captures["schema_version"] == 2, "capture-sources.json.schema_version", "expected version 2 with page-bound screenshots and DOM targets")
        self.sources(captures)
        self.current_sources(captures)
        slides, shots = deck.get("slides"), captures.get("shots")
        if not self.require(isinstance(slides, list) and bool(slides), "slides.json.slides", "expected a non-empty array"):
            slides = []
        if not self.require(isinstance(shots, list), "capture-sources.json.shots", "expected a capture entry for every page"):
            shots = []
        self.slide_count, self.shot_count = len(slides), len(shots)
        catalog: dict[Any, dict[str, Any]] = {}
        for index, shot in enumerate(shots):
            where = f"capture-sources.json.shots[{index}]"
            if not self.require(isinstance(shot, dict) and page_id(shot.get("page_id")), where, "expected an object with a stable page_id"):
                continue
            key = shot["page_id"]
            if self.require(key not in catalog, where, f"duplicate page_id {key!r}"):
                catalog[key] = shot
        seen: set[Any] = set()
        for index, slide in enumerate(slides):
            where = f"slides.json.slides[{index}]"
            if not self.require(isinstance(slide, dict) and page_id(slide.get("id")), where, "every page needs a stable id"):
                continue
            key = slide["id"]
            self.require(key not in seen, where, f"duplicate page id {key!r}")
            seen.add(key)
            self.require(key in catalog, where, f"no capture-sources.json shot for page {key!r}; recapture this page")
            shot = catalog.get(key, {})
            context = slide.get("capture_context", "task-historical")
            shot_context = shot.get("source_context", "task-historical")
            self.require(context == shot_context, where, "slide and screenshot refer to different source contexts")
            if context != "task-historical":
                current = captures.get("current_ui_source") or {}
                self.require(isinstance(current, dict) and current.get("source_id") == context, where, "current screenshot needs its own verified source context")
            self.capture(slide, shot, f"page[{key}]")
        if not self.captures_only:
            self.generated(slides)
        return {"status": "FAIL" if self.errors else "PASS", "mode": "captures-only" if self.captures_only else "full", "slide_count": self.slide_count, "shot_count": self.shot_count, "current_ui_status": self.current_ui_status, "error_count": len(self.errors), "errors": self.errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures-only", action="store_true", help="Check captures, markers, and UI source hashes before rebuilding generated files.")
    parser.add_argument("--json", action="store_true", help="Print the complete machine-readable report.")
    parser.add_argument("--guide-dir", type=Path, default=GUIDE, help="Guide directory (defaults to this script's directory).")
    parser.add_argument("--repo-root", type=Path, default=GUIDE.parents[2], help="Repository root for UI source hashes.")
    args = parser.parse_args()
    result = Verifier(args.guide_dir, args.repo_root, args.captures_only).run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']} · {result['mode']} · {result['slide_count']} pages · {result['shot_count']} captures · {result['error_count']} errors")
        for error in result["errors"][:20]:
            print(f"- {error}")
        if result["error_count"] > 20:
            print(f"- {result['error_count'] - 20} more errors; rerun with --json for all diagnostics.")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
