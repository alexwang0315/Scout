from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pydantic_ai_runtime_compat import (  # noqa: E402
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_native_research_capabilities_for_model,
    pydantic_native_research_trace,
    pydantic_result_output,
)
from scout.agents.model_policy import resolve_model_policy  # noqa: E402
from scout_env import load_scout_env_files  # noqa: E402

ARTIFACT_KIND = "scout_ai_route_context_briefing_variants"
ARTIFACT_VERSION = "scout_ai_route_context_briefing_variants.v1"
PLAN_KIND = "scout_ai_route_context_briefing_variants_plan"
PLAN_VERSION = "scout_ai_route_context_briefing_variants_plan.v1"
DEFAULT_MODEL = "nvidia:z-ai/glm-5.2"
DEFAULT_OUTPUT_DIR = "outputs/briefings/route_context_variants_ai_once"
DEFAULT_BASELINE_REF = "outputs/briefings/route_context_briefing.template_backup.20260705T051214Z.html"
DEFAULT_SKILL_REF = "skills/scout/route-context-intelligence.yaml"
DEFAULT_MAX_POINTS = 72
DEFAULT_MAX_IMAGES = 8
DEFAULT_REFERENCE_SIMILARITY_NGRAM = 4

BLOCKED_VISIBLE_TERMS = (
    "candidate_only",
    "runtime_safety_truth",
    "prompt",
    "model output",
    "compiler",
    "cache path",
    "artifact path",
    "source tier machine",
    "JSON plan",
    "material board",
    "image guide",
    "speaker note",
    "visual kit",
    "opening visual",
    "photo readiness",
    "page preparation",
    "Scout AI",
    "route_context_pack.json",
    "workspace cache",
    "行前照片與地圖狀態",
    "已檢查開場",
    "開場主視覺",
    "行程畫面覆蓋",
    "畫面偏薄",
    "圖像導覽",
    "畫面索引",
    "把可用圖片一次攤開",
    "素材板",
    "提示詞",
    "產生方式",
    "內部查核",
    "模型輸出",
    "候選證據",
    "安全真相",
)

BAD_IMAGE_TERMS = (
    "icon",
    "logo",
    "logotype",
    "button",
    "menu",
    "search",
    "close",
    "language",
    "facebook",
    "tracking",
    "pixel",
    "avatar",
    "badge",
    "sprite",
)

THEME_CLASSES = (
    "editorial-atlas",
    "expedition-command",
    "field-notebook",
    "topographic-magazine",
    "night-navigation",
)
VARIANT_OUTPUT_REFS = (
    "01-magazine_atlas.html",
    "02-command_wall.html",
    "03-field_notebook.html",
    "04-topographic_feature.html",
    "05-night_navigation.html",
)


class ModelRunner(Protocol):
    model_name: str
    last_prompt: str | None
    last_response: str | None
    last_usage: dict[str, Any] | None
    last_native_research_trace: dict[str, Any] | None

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        ...


@dataclass(frozen=True)
class WrittenOutputs:
    output_dir: Path
    plan_ref: str
    comparison_json_ref: str
    comparison_md_ref: str
    index_ref: str
    variant_refs: tuple[str, ...]


class UsageRecordingPydanticAIRunner:
    def __init__(
        self,
        *,
        model_name: str,
        model_max_tokens: int,
    ) -> None:
        self.model_name = model_name
        self.model_max_tokens = model_max_tokens
        self.last_prompt: str | None = None
        self.last_response: str | None = None
        self.last_usage: dict[str, Any] | None = None
        self.last_native_research_trace: dict[str, Any] | None = None

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        self.last_prompt = prompt

        def run_once(call_prompt: str) -> str:
            from pydantic_ai import Agent

            policy = resolve_model_policy(self.model_name)
            chat_model_name = policy.model_for_agent or self.model_name
            agent = Agent(
                build_chat_model(model_name=chat_model_name),
                system_prompt=(
                    "Scout AI route-context-intelligence briefing generator. "
                    "Before returning the plan, use WebSearch at least once and "
                    "WebFetch at least once for current public route context; search "
                    "snippets are not evidence. If one fetched URL fails, choose "
                    "another public Search result and continue. Return strict JSON "
                    "only. Do not "
                    "mutate Scout runtime, "
                    "hardware, safety, transport, or workspace canonical briefing."
                ),
                capabilities=pydantic_native_research_capabilities_for_model(
                    chat_model_name
                ),
                **pydantic_agent_runtime_kwargs(),
            )
            result = agent.run_sync(
                call_prompt,
                model_settings={"max_tokens": self.model_max_tokens},
            )
            output = str(pydantic_result_output(result))
            self.last_response = output
            self.last_usage = _usage_to_dict(getattr(result, "usage", None))
            self.last_native_research_trace = pydantic_native_research_trace(result)
            if (
                self.last_native_research_trace["web_search_call_count"] < 1
                or self.last_native_research_trace["web_fetch_call_count"] < 1
            ):
                raise ValueError(
                    "Scout AI variants generation did not complete the required "
                    "WebSearch -> WebFetch research handoff"
                )
            return output

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_once, prompt)
        try:
            output = future.result(timeout=timeout_seconds)
            self.last_response = output
            if self.last_usage is None:
                self.last_usage = _estimated_usage(prompt=prompt, response=output)
            return output
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("pydantic route-context variant provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def generate_route_context_briefing_variants(
    *,
    project_root: Path,
    baseline_html: Path,
    skill_path: Path,
    output_dir: Path,
    runner: ModelRunner,
    timeout_seconds: int,
    reference_variants_dir: Path | None = None,
    max_reference_similarity: float | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or _utc_now()
    workspace = _load_workspace_evidence(project_root)
    skill_text = skill_path.read_text(encoding="utf-8")
    skill_manifest = yaml.safe_load(skill_text)
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_variants = _load_reference_variant_specs(reference_variants_dir)
    prompt = build_variants_prompt(
        workspace=workspace,
        skill_manifest=skill_manifest,
        skill_text=skill_text,
        baseline_html=baseline_html,
        reference_variants=reference_variants,
        max_reference_similarity=max_reference_similarity,
    )
    raw_output = runner.run(prompt, timeout_seconds=timeout_seconds)
    try:
        plan = parse_model_plan(raw_output)
        plan = attach_model_record(
            plan,
            prompt=prompt,
            response=raw_output,
            usage=getattr(runner, "last_usage", None),
            native_research=getattr(runner, "last_native_research_trace", None),
        )
        _validate_model_plan(plan)
    except Exception as exc:
        failure_ref = write_failure_artifact(
            output_dir=output_dir,
            model_name=getattr(runner, "model_name", "unknown"),
            skill_path=skill_path,
            skill_text=skill_text,
            prompt=prompt,
            response=raw_output,
            usage=getattr(runner, "last_usage", None),
            error=exc,
            generated_at=generated_at,
        )
        raise ValueError(
            f"Scout AI route-context variants response failed validation; "
            f"failure artifact: {failure_ref}"
        ) from exc
    written = write_variant_outputs(
        project_root=project_root,
        output_dir=output_dir,
        baseline_html=baseline_html,
        workspace=workspace,
        skill_manifest=skill_manifest,
        skill_text=skill_text,
        model_name=getattr(runner, "model_name", "unknown"),
        raw_model_output=raw_output,
        plan=plan,
        generated_at=generated_at,
        reference_variants=reference_variants,
        reference_variants_dir=reference_variants_dir,
        max_reference_similarity=max_reference_similarity,
    )
    comparison = _read_json(output_dir / written.comparison_json_ref)
    return {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": ARTIFACT_VERSION,
        "status": "completed",
        "generated_at": generated_at,
        "project_root": str(project_root),
        "model": getattr(runner, "model_name", "unknown"),
        "skill_id": skill_manifest.get("id"),
        "skill_version": skill_manifest.get("version"),
        "output_dir": str(written.output_dir),
        "plan_ref": written.plan_ref,
        "comparison_json_ref": written.comparison_json_ref,
        "comparison_md_ref": written.comparison_md_ref,
        "index_ref": written.index_ref,
        "variant_refs": list(written.variant_refs),
        "reference_similarity_gate": comparison.get("reference_similarity_gate"),
    }


def build_variants_prompt(
    *,
    workspace: dict[str, Any],
    skill_manifest: dict[str, Any],
    skill_text: str,
    baseline_html: Path,
    reference_variants: list[dict[str, Any]] | None = None,
    max_reference_similarity: float | None = None,
) -> str:
    skill_summary = {
        "id": skill_manifest.get("id"),
        "version": skill_manifest.get("version"),
        "triggers": skill_manifest.get("triggers", []),
        "activation_gate": skill_manifest.get("activation_gate", {}),
        "layout_contract": (
            skill_manifest.get("output_schema", {}).get("layout_contract", {})
        ),
        "application_routing": skill_manifest.get("application_routing", {}),
    }
    prompt_payload = {
        "route_summary": workspace["route_summary"],
        "workspace_counts": workspace["counts"],
        "top_points": workspace["top_points"][:8],
        "sec6_layer_examples": {
            key: value[:3]
            for key, value in workspace["sec6_layer_examples"].items()
        },
        "media": workspace["media"][:6],
        "sources": workspace["sources"][:10],
        "baseline_reference": {
            "path": str(baseline_html),
            "purpose": "quality comparison only; do not copy its copy or layout",
        },
        "blocked_visible_terms": BLOCKED_VISIBLE_TERMS,
        "skill_summary": skill_summary,
        "skill_contract_excerpt": skill_text[:2000],
    }
    if reference_variants:
        prompt_payload["reference_variants_to_avoid"] = [
            {
                "slug": item.get("slug"),
                "title": item.get("title"),
                "tone": item.get("tone"),
                "concept": item.get("concept"),
                "copy_excerpt": item.get("copy_excerpt"),
            }
            for item in reference_variants[:5]
        ]
        prompt_payload["reference_similarity_gate"] = {
            "metric": "visible briefing copy 4-gram cosine",
            "max_allowed": max_reference_similarity,
            "note": (
                "Avoid matching reference titles, tones, concepts, section frames, "
                "chapter naming patterns, observation prompts, and point-angle wording."
            ),
        }
    if reference_variants:
        concept_instruction = (
            "Reference variants are supplied in workspace evidence. Generate five NEW versions that are "
            "not magazine atlas, command-wall expedition board, field notebook, topographic feature issue, "
            "or night-navigation briefing. Use five different route-facing frames instead: "
            "one leader rehearsal run-through, one ridge-and-valley transect board, one hut-to-summit "
            "itinerary ledger, one weather-season checkpoint review, and one source-evidence courtroom. "
            "Do not reuse reference titles, tones, section metaphors, chart names, chapter naming patterns, "
            "or observation prompt wording. The deterministic gate will compare your visible briefing copy "
            f"against the reference set and fail any variant above {max_reference_similarity or 0.6:.2f} cosine similarity. "
            "Do not invent route facts outside the supplied workspace evidence.\n\n"
        )
    else:
        concept_instruction = (
            "Make the five versions substantially different in editorial concept: one magazine atlas, "
            "one command-wall expedition board, one field notebook, one topographic feature issue, "
            "and one night-navigation briefing. Do not copy prior briefing text. Do not invent route facts "
            "outside the supplied workspace evidence.\n\n"
        )
    return (
        "You are Scout AI executing the route-context-intelligence skill. "
        "Generate exactly five complete route-content briefing variant specs in one model call. "
        "The deterministic Scout renderer will only place your provided variant copy, "
        "headings, section order, visual direction, and selected workspace evidence into HTML. "
        "Codex or the renderer must not add extra story copy after this response.\n\n"
        "Output strict JSON only. No Markdown fences, no reasoning, no explanation. "
        "Your first character must be { and your last character must be }. "
        "Use this exact top-level shape:\n"
        "{"
        f"\"artifact_kind\":\"{PLAN_KIND}\","
        f"\"schema_version\":\"{PLAN_VERSION}\","
        "\"skill_id\":\"route-context-intelligence\","
        "\"one_model_call_complete\":true,"
        "\"no_codex_posthoc_supplement\":true,"
        "\"variants\":[... five variant objects ...]"
        "}\n\n"
        "Hard length rule: the entire JSON response must stay under 5000 output tokens. "
        "Every string field must be concise Traditional Chinese route-briefing copy: "
        "title/subtitle under 28 Chinese characters, editorial_thesis/source_storyline/"
        "leader_review_focus/closing_note under 70 Chinese characters, chapter_titles "
        "under 18 Chinese characters each, observation_prompts and point angle fields "
        "under 28 Chinese characters each. Do not write paragraphs.\n\n"
        "Each variant object must include: slug, title, subtitle, tone, concept, "
        "editorial_thesis, hero_caption, nav_labels (6 strings), "
        "layer_headlines (historical/cultural/natural/terrain/seasonal/observation), "
        "chapter_titles (at least 6 strings), observation_prompts (at least 6 strings), "
        "point_angles (at least 8 objects with label, angle, question, route_reading), "
        "chart_titles (at least 4 strings), source_storyline, leader_review_focus, closing_note. "
        "Keep each field short; the renderer will apply these complete specs to workspace evidence.\n\n"
        "Visible product copy must talk only about the trip, route segment, source, lodging or "
        "intermediate point, terrain, weather/season, observation stop, or leader review task. "
        "Do not include internal terms such as candidate_only, runtime_safety_truth, prompt, model, "
        "compiler, cache, JSON plan, artifact path, Scout AI, source tier machine field, visual kit, "
        "image guide, material board, opening visual, photo readiness, or page preparation in any "
        "visible copy field. Use normal Traditional Chinese route-briefing language.\n\n"
        f"{concept_instruction}"
        f"Workspace evidence JSON: {json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)}"
    )


def parse_model_plan(raw_output: str) -> dict[str, Any]:
    text = str(raw_output or "").strip()
    candidates = _fenced_json_candidates(text)
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        payload = candidate.strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            first_brace = payload.find("{")
            if first_brace < 0:
                continue
            try:
                parsed, _end = decoder.raw_decode(payload[first_brace:])
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Scout AI route-context variants response did not contain JSON")


def write_variant_outputs(
    *,
    project_root: Path,
    output_dir: Path,
    baseline_html: Path,
    workspace: dict[str, Any],
    skill_manifest: dict[str, Any],
    skill_text: str,
    model_name: str,
    raw_model_output: str,
    plan: dict[str, Any],
    generated_at: str,
    reference_variants: list[dict[str, Any]] | None = None,
    reference_variants_dir: Path | None = None,
    max_reference_similarity: float | None = None,
) -> WrittenOutputs:
    skill_hash = hashlib.sha256(skill_text.encode("utf-8")).hexdigest()
    raw_output_hash = hashlib.sha256(raw_model_output.encode("utf-8")).hexdigest()
    prompt_content = getattr_model_attr(plan, "_prompt_content")
    token_usage = getattr_model_attr(plan, "_token_usage")
    response_content = getattr_model_attr(plan, "_response_content") or raw_model_output
    parsed_plan = {key: value for key, value in plan.items() if not key.startswith("_")}
    plan_payload = {
        "artifact_kind": "scout_ai_route_context_briefing_variants_model_plan",
        "schema_version": "scout_ai_route_context_briefing_variants_model_plan.v1",
        "generated_at": generated_at,
        "model": model_name,
        "skill_manifest_ref": str(Path(DEFAULT_SKILL_REF)),
        "skill_manifest_sha256": skill_hash,
        "model_output_sha256": raw_output_hash,
        "token_usage": token_usage,
        "prompt_content": prompt_content,
        "response_content": response_content,
        "raw_model_output": raw_model_output,
        "parsed_plan": parsed_plan,
        "boundary": {
            "api_key_embedded": False,
            "raw_prompt_embedded": True,
            "raw_response_embedded": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "workspace_canonical_briefing_overwritten": False,
        },
    }
    plan_ref = "scout_ai_route_context_variant_model_plan.json"
    comparison_json_ref = "route_context_variant_comparison.json"
    comparison_md_ref = "route_context_variant_comparison.md"
    index_ref = "index.html"
    failure_ref = "scout_ai_route_context_variant_model_failure.json"
    _remove_stale_variant_html(output_dir, keep={index_ref, *VARIANT_OUTPUT_REFS})
    _remove_stale_failure_artifact(output_dir / failure_ref)
    (output_dir / plan_ref).write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    variants = plan["variants"]
    variant_refs: list[str] = []
    variant_reports: list[dict[str, Any]] = []
    baseline_report = analyze_html(baseline_html, slug="baseline template")
    for index, variant in enumerate(variants, start=1):
        theme = THEME_CLASSES[(index - 1) % len(THEME_CLASSES)]
        slug = _safe_slug(str(variant.get("slug") or f"variant-{index:02d}"))
        if not slug.startswith(f"{index:02d}-"):
            slug = f"{index:02d}-{slug}"
        html_text = render_variant_html(
            variant=variant,
            workspace=workspace,
            theme=theme,
            skill_id=str(skill_manifest.get("id") or "route-context-intelligence"),
            generated_at=generated_at,
        )
        file_name = (
            f"{slug}.html"
            if reference_variants
            else (
                VARIANT_OUTPUT_REFS[index - 1]
                if index <= len(VARIANT_OUTPUT_REFS)
                else f"{slug}.html"
            )
        )
        html_path = output_dir / file_name
        html_path.write_text(html_text, encoding="utf-8")
        report = analyze_html(html_path, slug=slug)
        report.update(
            {
                "tone": variant.get("tone"),
                "concept": variant.get("concept"),
                "file": str(html_path),
                "relative_ref": file_name,
                "passes_richness_gate": report["visible_chars"]
                >= baseline_report["visible_chars"],
                "passes_unrelated_terms_gate": not report["unrelated_terms"],
                "passes_bad_image_gate": not report["bad_image_refs"],
                "generated_by_single_model_plan": True,
                "codex_posthoc_supplement": False,
            }
        )
        reference_similarity = _reference_similarity_report(
            variant,
            reference_variants=reference_variants or [],
            max_reference_similarity=max_reference_similarity,
        )
        if reference_similarity is not None:
            report["reference_similarity"] = reference_similarity
            report["max_reference_similarity"] = reference_similarity["max_score"]
            report["passes_reference_similarity_gate"] = reference_similarity[
                "passes_gate"
            ]
        variant_refs.append(file_name)
        variant_reports.append(report)

    reference_gate = _reference_similarity_gate_summary(
        reference_variants=reference_variants or [],
        reference_variants_dir=reference_variants_dir,
        max_reference_similarity=max_reference_similarity,
        variant_reports=variant_reports,
    )
    comparison = {
        "artifact_kind": "scout_ai_route_context_briefing_variant_comparison",
        "schema_version": "scout_ai_route_context_briefing_variant_comparison.v1",
        "generated_at": generated_at,
        "project_root": str(project_root),
        "baseline": baseline_report,
        "skill_id": skill_manifest.get("id"),
        "skill_version": skill_manifest.get("version"),
        "model": model_name,
        "model_output_sha256": raw_output_hash,
        "one_model_call_complete": bool(plan.get("one_model_call_complete")),
        "no_codex_posthoc_supplement": bool(plan.get("no_codex_posthoc_supplement")),
        "variants": variant_reports,
    }
    if reference_gate is not None:
        comparison["reference_similarity_gate"] = reference_gate
    (output_dir / comparison_json_ref).write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / comparison_md_ref).write_text(
        _comparison_markdown(comparison),
        encoding="utf-8",
    )
    (output_dir / index_ref).write_text(
        _index_html(comparison),
        encoding="utf-8",
    )
    if reference_gate is not None and reference_gate["status"] == "failed":
        failures = [
            f"{item['slug']}={item['max_reference_similarity']:.3f}"
            for item in variant_reports
            if item.get("passes_reference_similarity_gate") is False
        ]
        raise ValueError(
            "Scout AI route-context variants failed reference similarity gate: "
            + ", ".join(failures)
        )
    return WrittenOutputs(
        output_dir=output_dir,
        plan_ref=plan_ref,
        comparison_json_ref=comparison_json_ref,
        comparison_md_ref=comparison_md_ref,
        index_ref=index_ref,
        variant_refs=tuple(variant_refs),
    )


def _remove_stale_variant_html(output_dir: Path, *, keep: set[str]) -> None:
    for html_path in output_dir.glob("*.html"):
        if html_path.name not in keep:
            html_path.unlink()


def _remove_stale_failure_artifact(path: Path) -> None:
    if path.exists():
        path.unlink()


def write_failure_artifact(
    *,
    output_dir: Path,
    model_name: str,
    skill_path: Path,
    skill_text: str,
    prompt: str,
    response: str,
    usage: dict[str, Any] | None,
    error: Exception,
    generated_at: str,
) -> str:
    ref = "scout_ai_route_context_variant_model_failure.json"
    payload = {
        "artifact_kind": "scout_ai_route_context_briefing_variants_model_failure",
        "schema_version": "scout_ai_route_context_briefing_variants_model_failure.v1",
        "generated_at": generated_at,
        "status": "failed",
        "model": model_name,
        "skill_manifest_ref": str(skill_path),
        "skill_manifest_sha256": hashlib.sha256(skill_text.encode("utf-8")).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "token_usage": usage or _estimated_usage(prompt=prompt, response=response),
        "prompt_content": prompt,
        "response_content": response,
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
        "boundary": {
            "api_key_embedded": False,
            "raw_prompt_embedded": True,
            "raw_response_embedded": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "workspace_canonical_briefing_overwritten": False,
        },
    }
    (output_dir / ref).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ref


def render_variant_html(
    *,
    variant: dict[str, Any],
    workspace: dict[str, Any],
    theme: str,
    skill_id: str,
    generated_at: str,
) -> str:
    route = workspace["route_summary"]
    title = _text(variant.get("title"), "山徑脈絡簡報")
    subtitle = _text(variant.get("subtitle"), "行前閱讀與路線觀察")
    thesis = _text(variant.get("editorial_thesis"), "")
    concept = _text(variant.get("concept"), "")
    hero_caption = _text(variant.get("hero_caption"), "")
    nav_labels = _string_list(variant.get("nav_labels"), limit=6)
    if len(nav_labels) < 6:
        nav_labels = ["路線", "影像", "地形", "文化", "季節", "來源"]
    images = workspace["media"][:DEFAULT_MAX_IMAGES]
    hero = images[0] if images else {}
    layer_headlines = variant.get("layer_headlines") if isinstance(variant.get("layer_headlines"), dict) else {}
    chapter_titles = _string_list(variant.get("chapter_titles"), limit=10)
    point_angles = _point_angles(variant)
    observation_prompts = _string_list(variant.get("observation_prompts"), limit=12)
    chart_titles = _string_list(variant.get("chart_titles"), limit=8)
    top_points = workspace["top_points"]
    source_cards = workspace["sources"][:12]
    layer_examples = workspace["sec6_layer_examples"]
    counts = workspace["counts"]

    sections = [
        _hero_section(
            title=title,
            subtitle=subtitle,
            thesis=thesis,
            concept=concept,
            hero=hero,
            hero_caption=hero_caption,
            route=route,
            nav_labels=nav_labels,
        ),
        _image_strip(images),
        _route_profile_section(route=route, counts=counts, chart_titles=chart_titles),
        _chapters_section(chapter_titles=chapter_titles, points=top_points, point_angles=point_angles),
        _six_layers_section(layer_headlines=layer_headlines, layer_examples=layer_examples),
        _observation_section(prompts=observation_prompts, points=top_points, point_angles=point_angles),
        _point_catalog_section(points=top_points, point_angles=point_angles),
        _source_section(source_cards=source_cards, source_counts=workspace["source_counts"]),
        _evidence_manifest_section(workspace=workspace),
        _leader_review_section(variant=variant, workspace=workspace),
    ]
    body = "\n".join(sections)
    return (
        "<!doctype html>\n"
        '<html lang="zh-Hant">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>{_css()}</style>\n"
        "</head>\n"
        f'<body class="{_esc(theme)}" data-skill-id="{_esc(skill_id)}" data-generated-at="{_esc(generated_at)}">\n'
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def analyze_html(path: Path, *, slug: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    visible = _visible_text(text)
    image_refs = re.findall(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", text, flags=re.I)
    bad_images = [
        src for src in image_refs if any(term in src.casefold() for term in BAD_IMAGE_TERMS)
    ]
    terms = [term for term in BLOCKED_VISIBLE_TERMS if term.casefold() in visible.casefold()]
    section_count = len(re.findall(r"<section\b", text, flags=re.I))
    article_count = len(re.findall(r"<article\b", text, flags=re.I))
    chart_count = len(
        re.findall(r'class="[^"]*(?:chart|meter|timeline|bar|profile|matrix)[^"]*"', text, flags=re.I)
    )
    denominator = max(1, section_count + article_count)
    innovation = round(
        min(
            100.0,
            62.0
            + min(18.0, chart_count * 1.8)
            + min(12.0, len(set(re.findall(r"class=\"([^\"]+)\"", text))) / 8)
            + (8.0 if "clip-path" in text or "mix-blend-mode" in text else 0.0),
        ),
        1,
    )
    return {
        "slug": slug,
        "file": str(path),
        "visible_chars": len(visible),
        "sections": section_count,
        "articles": article_count,
        "images": len(image_refs),
        "chart_like_blocks": chart_count,
        "chart_ratio": round(chart_count / denominator, 3),
        "richness_score": round(
            min(120.0, len(visible) / 220 + article_count * 0.35 + section_count * 0.8),
            1,
        ),
        "innovation_score": innovation,
        "unrelated_terms": terms,
        "bad_image_refs": bad_images,
    }


def _load_reference_variant_specs(reference_variants_dir: Path | None) -> list[dict[str, Any]]:
    if reference_variants_dir is None:
        return []
    reference_dir = reference_variants_dir.expanduser().resolve()
    plan_path = reference_dir / "scout_ai_route_context_variant_model_plan.json"
    plan_payload = _read_json(plan_path)
    parsed_plan = plan_payload.get("parsed_plan") if isinstance(plan_payload, dict) else {}
    variants = parsed_plan.get("variants") if isinstance(parsed_plan, dict) else None
    if not isinstance(variants, list):
        return []
    specs: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            continue
        copy_text = _variant_copy_text(variant)
        specs.append(
            {
                "slug": str(variant.get("slug") or f"reference-{index:02d}"),
                "title": variant.get("title"),
                "tone": variant.get("tone"),
                "concept": variant.get("concept"),
                "copy_text": copy_text,
                "copy_excerpt": copy_text[:700],
                "source_plan_ref": str(plan_path),
            }
        )
    return specs[:5]


def _reference_similarity_report(
    variant: dict[str, Any],
    *,
    reference_variants: list[dict[str, Any]],
    max_reference_similarity: float | None,
) -> dict[str, Any] | None:
    if not reference_variants:
        return None
    copy_text = _variant_copy_text(variant)
    scores = []
    for reference in reference_variants:
        score = _ngram_cosine_similarity(
            copy_text,
            str(reference.get("copy_text") or ""),
            n=DEFAULT_REFERENCE_SIMILARITY_NGRAM,
        )
        scores.append(
            {
                "reference_slug": reference.get("slug"),
                "score": round(score, 4),
            }
        )
    most_similar = max(scores, key=lambda item: float(item["score"]), default=None)
    max_score = float(most_similar["score"]) if most_similar else 0.0
    return {
        "metric": f"model_copy_{DEFAULT_REFERENCE_SIMILARITY_NGRAM}gram_cosine",
        "max_allowed": max_reference_similarity,
        "max_score": round(max_score, 4),
        "most_similar_reference": most_similar.get("reference_slug") if most_similar else None,
        "scores": scores,
        "passes_gate": (
            True
            if max_reference_similarity is None
            else max_score <= max_reference_similarity
        ),
        "fixed_route_evidence_excluded": True,
    }


def _reference_similarity_gate_summary(
    *,
    reference_variants: list[dict[str, Any]],
    reference_variants_dir: Path | None,
    max_reference_similarity: float | None,
    variant_reports: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not reference_variants:
        return None
    failures = [
        item
        for item in variant_reports
        if item.get("passes_reference_similarity_gate") is False
    ]
    max_score = max(
        [float(item.get("max_reference_similarity") or 0.0) for item in variant_reports]
        or [0.0]
    )
    return {
        "enabled": True,
        "status": "failed" if failures else "passed",
        "metric": f"model_copy_{DEFAULT_REFERENCE_SIMILARITY_NGRAM}gram_cosine",
        "max_allowed": max_reference_similarity,
        "max_observed": round(max_score, 4),
        "reference_variant_count": len(reference_variants),
        "reference_variants_dir": str(reference_variants_dir) if reference_variants_dir else None,
        "fixed_route_evidence_excluded": True,
        "reason": (
            "The full HTML repeats mandatory route points, source tables, and renderer structure; "
            "this gate compares Scout AI generated visible briefing copy, concepts, headings, "
            "chapter titles, observation prompts, and point-angle wording."
        ),
        "failed_variants": [
            {
                "slug": item.get("slug"),
                "max_reference_similarity": item.get("max_reference_similarity"),
                "most_similar_reference": (
                    item.get("reference_similarity", {}).get("most_similar_reference")
                    if isinstance(item.get("reference_similarity"), dict)
                    else None
                ),
            }
            for item in failures
        ],
    }


def _variant_copy_text(variant: dict[str, Any]) -> str:
    keys = (
        "slug",
        "title",
        "subtitle",
        "tone",
        "concept",
        "editorial_thesis",
        "hero_caption",
        "nav_labels",
        "layer_headlines",
        "chapter_titles",
        "observation_prompts",
        "point_angles",
        "chart_titles",
        "source_storyline",
        "leader_review_focus",
        "closing_note",
    )
    chunks: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                chunks.append(stripped)
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
        elif value is not None:
            chunks.append(str(value))

    for key in keys:
        walk(variant.get(key))
    return " ".join(chunks)


def _ngram_cosine_similarity(left: str, right: str, *, n: int) -> float:
    left_counts = _ngram_counts(left, n=n)
    right_counts = _ngram_counts(right, n=n)
    if not left_counts or not right_counts:
        return 0.0
    dot = sum(count * right_counts.get(token, 0) for token, count in left_counts.items())
    left_norm = sum(count * count for count in left_counts.values()) ** 0.5
    right_norm = sum(count * count for count in right_counts.values()) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _ngram_counts(text: str, *, n: int) -> Counter[str]:
    normalized = re.sub(r"\s+", "", text.casefold())
    if not normalized:
        return Counter()
    if len(normalized) < n:
        return Counter({normalized: 1})
    return Counter(normalized[index : index + n] for index in range(len(normalized) - n + 1))


def _load_workspace_evidence(project_root: Path) -> dict[str, Any]:
    project = _read_json(project_root / "project.json")
    route_summary = _read_json(project_root / "normalized" / "routes" / "route_summary.json")
    route_context_pack = _read_json(
        project_root / "normalized" / "context" / "route_context" / "route_context_pack.json"
    )
    points_payload = _read_json(project_root / "candidates" / "route_context_points.json")
    source_manifest = _read_json(
        project_root / "normalized" / "context" / "route_context" / "source_manifest.json"
    )
    media_manifest = _read_json(
        project_root / "normalized" / "context" / "route_context" / "media_manifest.json"
    )
    web_case = _read_json(project_root / "outputs" / "layers" / "normalized" / "web_case_evidence.json")
    points = points_payload.get("points") if isinstance(points_payload.get("points"), list) else []
    ranked_points = sorted(points, key=_point_rank_key, reverse=True)
    top_points = [_compact_point(point) for point in ranked_points[:DEFAULT_MAX_POINTS]]
    layer_examples = _layer_examples(ranked_points)
    media = _collect_media(media_manifest, web_case)
    sources = _compact_sources(source_manifest, web_case)
    source_counts = {
        "loaded": sum(1 for item in source_manifest.get("source_report", []) if item.get("status") == "loaded"),
        "missing": sum(1 for item in source_manifest.get("source_report", []) if item.get("status") == "missing"),
        "total": len(source_manifest.get("source_report", [])),
        "by_tier": source_manifest.get("source_tiers", {}),
    }
    return {
        "project": _compact_dict(project, 20),
        "route_summary": _compact_dict(route_summary, 20),
        "counts": {
            "route_context_point_count": route_context_pack.get("point_count") or points_payload.get("point_count"),
            "route_mileage_k_anchor_count": route_context_pack.get("route_mileage_k_anchor_count"),
            "by_sec6_layer": points_payload.get("counts", {}).get("by_sec6_layer", {}),
            "by_source_tier": points_payload.get("counts", {}).get("by_source_tier", {}),
            "media_count": len(media),
            "web_case_network_calls_made": web_case.get("boundary", {}).get("network_calls_made"),
            "live_source_refresh_status": source_manifest.get("live_source_refresh_evidence", {}).get("status"),
        },
        "source_counts": source_counts,
        "top_points": top_points,
        "sec6_layer_examples": layer_examples,
        "media": media,
        "sources": sources,
    }


def _collect_media(media_manifest: dict[str, Any], web_case: dict[str, Any]) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    for key in ("hero_image",):
        item = media_manifest.get(key)
        if isinstance(item, dict):
            media.append(_compact_media(item))
    for key in ("gallery_images", "images"):
        for item in media_manifest.get(key, []) if isinstance(media_manifest.get(key), list) else []:
            if isinstance(item, dict):
                media.append(_compact_media(item))
    for item in web_case.get("evidence_items", []) if isinstance(web_case.get("evidence_items"), list) else []:
        for image in item.get("image_refs", []) if isinstance(item.get("image_refs"), list) else []:
            if isinstance(image, dict):
                media.append(_compact_media(image))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in media:
        url = str(item.get("url") or item.get("src") or "").strip()
        if not url or url in seen or _is_bad_image_url(url):
            continue
        seen.add(url)
        deduped.append(item)
    return deduped[:DEFAULT_MAX_IMAGES]


def _compact_media(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": item.get("url") or item.get("src"),
        "caption": item.get("caption") or item.get("alt") or item.get("label") or item.get("title"),
        "context_layer": item.get("context_layer") or item.get("sec6_layer"),
        "source_tier": item.get("source_tier"),
        "source_family": item.get("source_family"),
        "page_url": item.get("page_url") or item.get("source_url"),
    }


def _compact_sources(source_manifest: dict[str, Any], web_case: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in source_manifest.get("source_report", []) if isinstance(source_manifest.get("source_report"), list) else []:
        if isinstance(item, dict):
            sources.append(
                {
                    "source_kind": item.get("source_kind"),
                    "status": item.get("status"),
                    "tier": item.get("tier") or item.get("source_tier"),
                    "role": item.get("role"),
                    "summary": item.get("summary") or item.get("reason"),
                }
            )
    for item in web_case.get("evidence_items", []) if isinstance(web_case.get("evidence_items"), list) else []:
        if isinstance(item, dict):
            sources.append(
                {
                    "source_kind": item.get("source_kind"),
                    "status": item.get("status", "loaded"),
                    "tier": item.get("source_tier"),
                    "role": item.get("context_layer"),
                    "title": item.get("title") or item.get("label"),
                    "summary": item.get("summary"),
                    "url": item.get("url"),
                }
            )
    return sources[:18]


def _layer_examples(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        for layer in point.get("sec6_layers", []) or []:
            if len(grouped[layer]) < 8:
                grouped[layer].append(_compact_point(point))
    return dict(grouped)


def _compact_point(point: dict[str, Any]) -> dict[str, Any]:
    score = point.get("observation_score")
    if isinstance(score, dict):
        score_value = score.get("value") or score.get("observation_value")
    else:
        score_value = None
    return {
        "label": point.get("display_label") or point.get("label"),
        "distance_m": point.get("distance_m"),
        "context_kind": point.get("context_kind"),
        "evidence_type": point.get("evidence_type"),
        "sec6_layers": point.get("sec6_layers", []),
        "source_tier": point.get("source_tier"),
        "source_families": point.get("source_families", []),
        "observation_value": score_value,
        "review_state": point.get("review_state"),
    }


def _point_rank_key(point: dict[str, Any]) -> tuple[float, float]:
    score = point.get("observation_score")
    value = 0.0
    if isinstance(score, dict):
        try:
            value = float(score.get("value") or score.get("observation_value") or 0.0)
        except (TypeError, ValueError):
            value = 0.0
    try:
        distance = float(point.get("distance_m") or 0.0)
    except (TypeError, ValueError):
        distance = 0.0
    return value, -distance


def _validate_model_plan(plan: dict[str, Any]) -> None:
    if plan.get("artifact_kind") != PLAN_KIND:
        raise ValueError(f"expected artifact_kind={PLAN_KIND}")
    if plan.get("schema_version") != PLAN_VERSION:
        raise ValueError(f"expected schema_version={PLAN_VERSION}")
    if plan.get("skill_id") != "route-context-intelligence":
        raise ValueError("model plan must declare skill_id=route-context-intelligence")
    if plan.get("one_model_call_complete") is not True:
        raise ValueError("model plan must declare one_model_call_complete=true")
    if plan.get("no_codex_posthoc_supplement") is not True:
        raise ValueError("model plan must declare no_codex_posthoc_supplement=true")
    variants = plan.get("variants")
    if not isinstance(variants, list) or len(variants) != 5:
        raise ValueError("model plan must contain exactly five variants")
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            raise ValueError(f"variant {index} must be an object")
        required = (
            "slug",
            "title",
            "subtitle",
            "tone",
            "concept",
            "editorial_thesis",
            "hero_caption",
            "nav_labels",
            "layer_headlines",
            "chapter_titles",
            "observation_prompts",
            "point_angles",
            "chart_titles",
            "source_storyline",
            "leader_review_focus",
            "closing_note",
        )
        missing = [key for key in required if key not in variant]
        if missing:
            raise ValueError(f"variant {index} missing required fields: {', '.join(missing)}")
        if len(_string_list(variant.get("chapter_titles"), limit=99)) < 6:
            raise ValueError(f"variant {index} must include at least six chapter titles")
        if len(_string_list(variant.get("observation_prompts"), limit=99)) < 6:
            raise ValueError(f"variant {index} must include at least six observation prompts")
        if len(_point_angles(variant)) < 8:
            raise ValueError(f"variant {index} must include at least eight point angles")


def _hero_section(
    *,
    title: str,
    subtitle: str,
    thesis: str,
    concept: str,
    hero: dict[str, Any],
    hero_caption: str,
    route: dict[str, Any],
    nav_labels: list[str],
) -> str:
    image_html = _image(hero, class_name="hero-img") if hero else ""
    stats = [
        ("總長", f"{float(route.get('distance_m') or 0) / 1000:.1f} km"),
        ("高度", f"{route.get('elevation_min_m', 'n/a')} - {route.get('elevation_max_m', 'n/a')} m"),
        ("點數", str(route.get("point_count") or "n/a")),
    ]
    nav = "".join(f'<a href="#s{i}">{_esc(label)}</a>' for i, label in enumerate(nav_labels, start=1))
    stat_html = "".join(
        f'<span><small>{_esc(label)}</small><b>{_esc(value)}</b></span>' for label, value in stats
    )
    return (
        '<section class="hero" id="s1">'
        '<div class="hero-copy">'
        f'<p class="kicker">{_esc(concept)}</p>'
        f"<h1>{_esc(title)}</h1>"
        f"<h2>{_esc(subtitle)}</h2>"
        f"<p>{_esc(thesis)}</p>"
        f'<div class="stat-row">{stat_html}</div>'
        f'<nav class="brief-nav">{nav}</nav>'
        "</div>"
        f'<figure>{image_html}<figcaption>{_esc(hero_caption or hero.get("caption") or "")}</figcaption></figure>'
        "</section>"
    )


def _image_strip(images: list[dict[str, Any]]) -> str:
    if not images:
        return '<section class="image-strip" id="s2"><h2>路線影像待補查</h2></section>'
    figures = []
    for image in images[:8]:
        figures.append(
            f'<figure>{_image(image)}<figcaption>{_esc(image.get("caption") or "")}</figcaption></figure>'
        )
    return f'<section class="image-strip" id="s2"><h2>照片綁定路線段落</h2><div class="image-grid">{"".join(figures)}</div></section>'


def _route_profile_section(
    *,
    route: dict[str, Any],
    counts: dict[str, Any],
    chart_titles: list[str],
) -> str:
    layer_counts = counts.get("by_sec6_layer", {}) if isinstance(counts.get("by_sec6_layer"), dict) else {}
    bars = []
    max_count = max([int(v) for v in layer_counts.values()] or [1])
    for layer, count in sorted(layer_counts.items()):
        width = int((int(count) / max_count) * 100)
        bars.append(
            f'<div class="bar"><span>{_esc(layer)}</span><i style="width:{width}%"></i><b>{int(count)}</b></div>'
        )
    chart_cards = "".join(
        f'<article class="chart-card"><h3>{_esc(title)}</h3><div class="meter-ring"><span>{idx}</span></div></article>'
        for idx, title in enumerate(chart_titles[:6], start=1)
    )
    return (
        '<section class="route-profile" id="s3">'
        "<h2>把路線拆成可討論的比例</h2>"
        '<div class="profile-grid">'
        f'<article class="profile-copy"><p>路線名稱：{_esc(route.get("route_name") or "未命名路線")}。'
        f'全段約 {float(route.get("distance_m") or 0) / 1000:.1f} 公里，'
        f'高度落差從 {route.get("elevation_min_m", "n/a")} m 到 {route.get("elevation_max_m", "n/a")} m。'
        "這裡先看行前脈絡比例，再決定哪些段落要講清楚。</p></article>"
        f'<article class="layer-bars">{"".join(bars)}</article>'
        f'<div class="chart-wall">{chart_cards}</div>'
        "</div></section>"
    )


def _chapters_section(
    *,
    chapter_titles: list[str],
    points: list[dict[str, Any]],
    point_angles: list[dict[str, str]],
) -> str:
    articles = []
    for idx, point in enumerate(points[:12]):
        angle = point_angles[idx % len(point_angles)] if point_angles else {}
        chapter = chapter_titles[idx % len(chapter_titles)] if chapter_titles else point.get("label", "")
        articles.append(
            '<article class="chapter-card">'
            f'<span>{idx + 1:02d}</span>'
            f'<h3>{_esc(chapter)}</h3>'
            f'<p><b>{_esc(point.get("label") or "")}</b>：{_esc(angle.get("angle") or _point_sentence(point))}</p>'
            f'<p class="question">{_esc(angle.get("question") or "這一段出發前要怎麼講給隊伍聽？")}</p>'
            "</article>"
        )
    return f'<section class="chapters" id="s4"><h2>行程章節</h2><div class="chapter-grid">{"".join(articles)}</div></section>'


def _six_layers_section(
    *,
    layer_headlines: dict[str, Any],
    layer_examples: dict[str, list[dict[str, Any]]],
) -> str:
    labels = {
        "historical": "歷史層",
        "cultural": "文化層",
        "natural": "自然層",
        "terrain": "地形層",
        "seasonal": "季節層",
        "observation": "觀察點",
    }
    cards = []
    for key, label in labels.items():
        examples = layer_examples.get(key, [])[:5]
        names = "、".join(_text(item.get("label"), "") for item in examples) or "出發前補查路段"
        headline = _text(layer_headlines.get(key), label) if isinstance(layer_headlines, dict) else label
        cards.append(
            '<article class="layer-card">'
            f'<h3>{_esc(label)}</h3>'
            f'<p>{_esc(headline)}</p>'
            f'<b>{_esc(names)}</b>'
            "</article>"
        )
    return f'<section class="six-layers" id="s5"><h2>六個行前面向</h2><div class="layer-grid">{"".join(cards)}</div></section>'


def _observation_section(
    *,
    prompts: list[str],
    points: list[dict[str, Any]],
    point_angles: list[dict[str, str]],
) -> str:
    cards = []
    for idx, point in enumerate(points[:18]):
        prompt = prompts[idx % len(prompts)] if prompts else "短停前先確認隊伍與路線節奏。"
        angle = point_angles[idx % len(point_angles)] if point_angles else {}
        cards.append(
            '<article class="observe-card">'
            f'<span>{idx + 1:02d}</span>'
            f'<h3>{_esc(point.get("label") or angle.get("label") or "路線點")}</h3>'
            f'<p>{_esc(angle.get("route_reading") or prompt)}</p>'
            f'<small>{_esc(prompt)}</small>'
            "</article>"
        )
    return f'<section class="observations" id="s6"><h2>值得停三分鐘討論的題目</h2><div class="observe-grid">{"".join(cards)}</div></section>'


def _source_section(
    *,
    source_cards: list[dict[str, Any]],
    source_counts: dict[str, Any],
) -> str:
    cards = []
    for idx, source in enumerate(source_cards[:12], start=1):
        cards.append(
            '<article class="source-card">'
            f'<span>{idx:02d}</span>'
            f'<h3>{_esc(source.get("title") or source.get("source_kind") or "來源")}</h3>'
            f'<p>{_esc(source.get("summary") or source.get("role") or source.get("status") or "")}</p>'
            f'<small>{_esc(source.get("tier") or "")} {_esc(source.get("source_kind") or "")}</small>'
            "</article>"
        )
    count_line = f"已載入 {source_counts.get('loaded', 0)} 類來源，待補查 {source_counts.get('missing', 0)} 類。"
    return f'<section class="sources" id="s7"><h2>資料來源如何支撐這趟路</h2><p>{_esc(count_line)}</p><div class="source-grid">{"".join(cards)}</div></section>'


def _point_catalog_section(
    *,
    points: list[dict[str, Any]],
    point_angles: list[dict[str, str]],
) -> str:
    cards = []
    for idx, point in enumerate(points[:67]):
        angle = point_angles[idx % len(point_angles)] if point_angles else {}
        layers = "、".join(point.get("sec6_layers", []) or []) or "待補面向"
        sources = "、".join(point.get("source_families", []) or []) or "來源待複核"
        review = point.get("review_state") or "待審查"
        value = point.get("observation_value")
        cards.append(
            '<article class="catalog-card matrix-card">'
            f'<span>{idx + 1:02d}</span>'
            f'<h3>{_esc(point.get("label") or angle.get("label") or "路線點")}</h3>'
            f'<p>{_esc(angle.get("route_reading") or _point_sentence(point))}</p>'
            f'<dl><dt>距離</dt><dd>{_esc(_distance_km(point.get("distance_m")))}</dd>'
            f'<dt>面向</dt><dd>{_esc(layers)}</dd>'
            f'<dt>來源</dt><dd>{_esc(point.get("source_tier") or "")} {_esc(sources)}</dd>'
            f'<dt>觀察值</dt><dd>{_esc(value if value is not None else "待評估")}</dd>'
            f'<dt>審查</dt><dd>{_esc(review)}</dd></dl>'
            f'<small>{_esc(angle.get("question") or "領隊出發前確認這個點和上下路段的關係。")}</small>'
            f'<p class="catalog-check">行前核對：把 {_esc(point.get("label") or "此點")} 對回地圖、照片、上下路段與隊伍節奏，確認它適合放在講解、快速通過或補查清單中的哪一類。</p>'
            f'<p class="catalog-check">隊伍討論：此點連到 {_esc(layers)}，來源線索為 {_esc(sources)}；若審查仍是 {_esc(review)}，簡報只能把它列為出發前要確認的路線脈絡。</p>'
            "</article>"
        )
    return (
        '<section class="point-catalog" id="s8">'
        "<h2>路線點資料牆</h2>"
        "<p>這一區把工作區內的路線脈絡點逐一攤開，供領隊對照行程段落、來源層、觀察價值與審查狀態。</p>"
        f'<div class="catalog-grid">{"".join(cards)}</div>'
        "</section>"
    )


def _evidence_manifest_section(*, workspace: dict[str, Any]) -> str:
    media_cards = []
    for idx, media in enumerate(workspace["media"][:DEFAULT_MAX_IMAGES], start=1):
        media_cards.append(
            '<article class="media-card">'
            f'<span>{idx:02d}</span>'
            f'<h3>{_esc(media.get("caption") or "路線影像")}</h3>'
            f'<p>{_esc(media.get("context_layer") or "路線段落影像")}；'
            f'{_esc(media.get("source_tier") or "")} {_esc(media.get("source_family") or "")}</p>'
            f'<small>{_esc(media.get("page_url") or media.get("url") or "")}</small>'
            "</article>"
        )
    layer_counts = workspace["counts"].get("by_sec6_layer", {})
    layer_rows = []
    if isinstance(layer_counts, dict):
        for layer, count in sorted(layer_counts.items()):
            layer_rows.append(
                f'<tr><th>{_esc(layer)}</th><td>{_esc(count)}</td>'
                "<td>此面向用於安排行前講解與路線觀察題。</td></tr>"
            )
    return (
        '<section class="evidence-manifest" id="s9">'
        "<h2>來源、影像與六層覆蓋</h2>"
        '<div class="manifest-grid">'
        f'<article><h3>六層覆蓋表</h3><table>{"".join(layer_rows)}</table></article>'
        f'<article><h3>路線影像索引</h3><div class="media-list">{"".join(media_cards)}</div></article>'
        "</div></section>"
    )


def _leader_review_section(
    *,
    variant: dict[str, Any],
    workspace: dict[str, Any],
) -> str:
    review = _text(variant.get("leader_review_focus"), "出發前先把路線段落、照片與短停問題對齊。")
    closing = _text(variant.get("closing_note"), "把這份簡報當作行前閱讀清單，現地決策另行確認。")
    points = workspace["top_points"][:8]
    items = "".join(
        f'<li><b>{_esc(point.get("label") or "")}</b><span>{_esc(_point_sentence(point))}</span></li>'
        for point in points
    )
    return (
        '<section class="leader-review" id="s8">'
        "<h2>領隊出發前最後確認</h2>"
        f"<p>{_esc(review)}</p>"
        f"<ul>{items}</ul>"
        f'<p class="closing">{_esc(closing)}</p>'
        "</section>"
    )


def _css() -> str:
    return """
:root{--ink:#17201b;--paper:#f8f2e5;--muted:#6f7469;--line:#263c34;--accent:#cf472f;--gold:#e6b450;--deep:#0f1715;--mist:#dfe6dc;--blue:#1f4b5b}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Avenir Next","PingFang TC","Hiragino Sans GB",sans-serif;letter-spacing:0;overflow-x:hidden}
section{padding:clamp(28px,5vw,70px);position:relative}h1,h2,h3,p{margin-top:0}h1{font-family:"Iowan Old Style","Songti TC",serif;font-size:clamp(44px,7vw,108px);line-height:.93;max-width:12ch}h2{font-family:"Iowan Old Style","Songti TC",serif;font-size:clamp(28px,4vw,64px);line-height:1.02}h3{font-size:clamp(18px,2vw,28px);line-height:1.18}p{font-size:clamp(15px,1.45vw,20px);line-height:1.68}.kicker{color:var(--accent);font-weight:800;text-transform:uppercase}.hero{min-height:92vh;display:grid;grid-template-columns:minmax(0,1.05fr) minmax(300px,.95fr);gap:32px;align-items:end;background:linear-gradient(120deg,var(--paper) 0%,#ebe4d1 55%,#d4dfd7 100%)}.hero figure{margin:0;align-self:stretch;display:flex;flex-direction:column;justify-content:flex-end}.hero-img,.image-grid img{width:100%;height:100%;min-height:360px;object-fit:cover;border:1px solid rgba(20,30,24,.24)}figcaption{font-size:14px;color:var(--muted);padding-top:8px}.stat-row{display:flex;flex-wrap:wrap;gap:10px;margin:24px 0}.stat-row span{border:1px solid var(--line);padding:10px 14px;min-width:120px}.stat-row small{display:block;color:var(--muted)}.stat-row b{font-size:22px}.brief-nav{display:flex;flex-wrap:wrap;gap:8px}.brief-nav a{color:inherit;text-decoration:none;border:1px solid var(--line);padding:8px 12px;background:rgba(255,255,255,.35)}.image-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.image-grid figure{margin:0;background:white}.image-grid img{aspect-ratio:4/3;min-height:0}.profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}.profile-copy,.layer-bars,.chart-card,.chapter-card,.layer-card,.observe-card,.source-card,.catalog-card,.media-card{border:1px solid rgba(23,32,27,.22);background:rgba(255,255,255,.42);padding:20px}.bar{display:grid;grid-template-columns:110px 1fr 40px;align-items:center;gap:10px;margin:10px 0}.bar i{display:block;height:14px;background:linear-gradient(90deg,var(--accent),var(--gold))}.chart-wall{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.meter-ring{width:92px;aspect-ratio:1;border:12px solid var(--gold);border-right-color:var(--accent);border-radius:50%;display:grid;place-items:center;font-size:28px;font-weight:900}.chapter-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.chapter-card span,.observe-card span,.source-card span,.catalog-card span,.media-card span{color:var(--accent);font-weight:900}.question{border-left:4px solid var(--gold);padding-left:10px}.layer-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}.observe-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.observe-card small{display:block;color:var(--muted);line-height:1.5}.source-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.catalog-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.catalog-card{min-width:0}.catalog-card p{font-size:15px}.catalog-card dl{display:grid;grid-template-columns:58px minmax(0,1fr);gap:4px 8px;margin:12px 0 0}.catalog-card dt{color:var(--muted);font-weight:800}.catalog-card dd{margin:0;overflow-wrap:anywhere}.catalog-card small,.media-card small{display:block;color:var(--muted);overflow-wrap:anywhere;line-height:1.45}.manifest-grid{display:grid;grid-template-columns:1fr 1.2fr;gap:18px}.manifest-grid table{width:100%;border-collapse:collapse}.manifest-grid th,.manifest-grid td{border-top:1px solid rgba(23,32,27,.22);padding:10px;text-align:left;vertical-align:top}.media-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.leader-review{background:var(--deep);color:#f6f0df}.leader-review ul{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:0;list-style:none}.leader-review li{border-top:1px solid rgba(255,255,255,.25);padding:14px 0}.leader-review span{display:block;color:#cbd6ca}.closing{font-size:24px;color:var(--gold)}
.editorial-atlas{--paper:#fbf1df;--ink:#1d241d;--accent:#b83624;--gold:#c9942d;--line:#314739}.editorial-atlas .hero{background:linear-gradient(100deg,#fbf1df 0%,#f6d8b8 46%,#d7e4db 100%)}.editorial-atlas .chapter-card:nth-child(2n){transform:translateY(12px)}
.expedition-command{--paper:#111713;--ink:#f5ead2;--muted:#aab6a6;--line:#89a08c;--accent:#ff5a3d;--gold:#ffd45a;background:#111713}.expedition-command .hero,.expedition-command section{background:#111713;color:#f5ead2}.expedition-command article,.expedition-command .profile-copy,.expedition-command .layer-bars{background:#18221d;border-color:#3a5446}.expedition-command .brief-nav a{background:#24372e}
.field-notebook{--paper:#f5edd4;--ink:#202015;--accent:#28604d;--gold:#d39c34}.field-notebook section{background-image:linear-gradient(rgba(32,32,21,.06) 1px,transparent 1px);background-size:100% 28px}.field-notebook article{border-style:dashed}
.topographic-magazine{--paper:#e9eee2;--ink:#10241d;--accent:#d24a32;--gold:#7a9638}.topographic-magazine section:before{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(160deg,rgba(16,36,29,.07) 0 1px,transparent 1px 18px);mix-blend-mode:multiply}.topographic-magazine>*{position:relative}
.night-navigation{--paper:#081014;--ink:#f0f2dc;--muted:#9eb0b5;--line:#47656b;--accent:#58d1ff;--gold:#f4c84a;background:#081014}.night-navigation section,.night-navigation .hero{background:#081014;color:#f0f2dc}.night-navigation article,.night-navigation .profile-copy,.night-navigation .layer-bars{background:#101d23;border-color:#31505a}.night-navigation .bar i{background:linear-gradient(90deg,#58d1ff,#f4c84a)}
@media(max-width:900px){.hero,.profile-grid,.manifest-grid{grid-template-columns:1fr}.image-grid,.chapter-grid,.observe-grid,.source-grid,.catalog-grid{grid-template-columns:1fr 1fr}.layer-grid{grid-template-columns:1fr 1fr}.leader-review ul{grid-template-columns:1fr}h1{max-width:100%}}
@media(max-width:560px){section{padding:24px 18px}.image-grid,.chapter-grid,.observe-grid,.source-grid,.catalog-grid,.media-list,.chart-wall,.layer-grid{grid-template-columns:1fr}.bar{grid-template-columns:86px 1fr 34px}.hero-img{min-height:260px}}
"""


def _comparison_markdown(comparison: dict[str, Any]) -> str:
    baseline = comparison["baseline"]
    reference_gate = comparison.get("reference_similarity_gate")
    lines = [
        "# Scout AI Route Context Briefing Variants",
        "",
        f"- model: `{comparison['model']}`",
        f"- skill: `{comparison['skill_id']}` v`{comparison['skill_version']}`",
        f"- one_model_call_complete: `{comparison['one_model_call_complete']}`",
        f"- no_codex_posthoc_supplement: `{comparison['no_codex_posthoc_supplement']}`",
    ]
    if isinstance(reference_gate, dict):
        lines.extend(
            [
                f"- reference_similarity_gate: `{reference_gate['status']}`",
                f"- reference_similarity_metric: `{reference_gate['metric']}`",
                f"- max_reference_similarity_observed: `{reference_gate['max_observed']}`",
                f"- max_reference_similarity_allowed: `{reference_gate['max_allowed']}`",
            ]
        )
    lines.extend(
        [
            "",
            "| 版本 | visible chars | sections/articles | images | chart ratio | richness | innovation | reference max | unrelated terms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| baseline | {baseline['visible_chars']} | "
                f"{baseline['sections']}/{baseline['articles']} | {baseline['images']} | "
                f"{baseline['chart_ratio']} | {baseline['richness_score']} | "
                f"{baseline['innovation_score']} | n/a | {len(baseline['unrelated_terms'])} |"
            ),
        ]
    )
    for item in comparison["variants"]:
        lines.append(
            f"| [{item['slug']}]({item['relative_ref']}) | {item['visible_chars']} | "
            f"{item['sections']}/{item['articles']} | {item['images']} | "
            f"{item['chart_ratio']} | {item['richness_score']} | "
            f"{item['innovation_score']} | {item.get('max_reference_similarity', 'n/a')} | "
            f"{len(item['unrelated_terms'])} |"
        )
    lines.append("")
    lines.append("## Gate Results")
    for item in comparison["variants"]:
        lines.append(
            f"- `{item['slug']}`: richness={item['passes_richness_gate']}, "
            f"unrelated_terms={item['passes_unrelated_terms_gate']}, "
            f"bad_images={item['passes_bad_image_gate']}, "
            f"reference_similarity={item.get('passes_reference_similarity_gate', 'n/a')}, "
            f"codex_posthoc_supplement={item['codex_posthoc_supplement']}."
        )
    lines.append("")
    return "\n".join(lines)


def _variant_file_href(ref: str) -> str:
    return f"?ref={quote(ref, safe='')}"


def _index_html(comparison: dict[str, Any]) -> str:
    cards = []
    for item in comparison["variants"]:
        reference_line = ""
        if "max_reference_similarity" in item:
            reference_line = (
                f"<li>reference similarity {item['max_reference_similarity']}</li>"
            )
        cards.append(
            "<article>"
            f'<h2><a href="{_esc(_variant_file_href(item["relative_ref"]))}">{_esc(item["slug"])}</a></h2>'
            f'<p>{_esc(item.get("concept") or item.get("tone") or "")}</p>'
            f"<ul><li>richness {item['richness_score']}</li>"
            f"<li>innovation {item['innovation_score']}</li>"
            f"<li>chart ratio {item['chart_ratio']}</li>"
            f"{reference_line}"
            f"<li>unrelated terms {len(item['unrelated_terms'])}</li></ul>"
            "</article>"
        )
    reference_gate = comparison.get("reference_similarity_gate")
    gate_html = ""
    if isinstance(reference_gate, dict):
        gate_html = (
            '<p class="gate">'
            f"Reference similarity gate: {_esc(reference_gate['status'])}; "
            f"max observed {_esc(reference_gate['max_observed'])} / "
            f"allowed {_esc(reference_gate['max_allowed'])}."
            "</p>"
        )
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Scout route briefing variants</title>"
        "<style>body{margin:0;background:#121610;color:#f6ecd8;font-family:'Avenir Next','PingFang TC',sans-serif;padding:42px}h1{font-size:clamp(36px,6vw,72px);font-family:'Iowan Old Style',serif}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}article{border:1px solid #6f765a;padding:20px;background:#1b2118}a{color:#ffd76a}</style>"
        "</head><body><h1>Scout AI 一次產生的 5 版 Route Briefing</h1>"
        "<p>這組頁面由 route-context-intelligence skill 的單次模型 plan 驅動，renderer 只使用 workspace evidence 排版。</p>"
        f"{gate_html}"
        f'<div class="grid">{"".join(cards)}</div>'
        f'<p><a href="{_esc(_variant_file_href("route_context_variant_comparison.md"))}">comparison markdown</a> · '
        f'<a href="{_esc(_variant_file_href("route_context_variant_comparison.json"))}">comparison json</a></p>'
        "</body></html>"
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def attach_model_record(
    plan: dict[str, Any],
    *,
    prompt: str,
    response: str,
    usage: dict[str, Any] | None,
    native_research: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan["_prompt_content"] = prompt
    plan["_response_content"] = response
    plan["_token_usage"] = usage or _estimated_usage(prompt=prompt, response=response)
    plan["_native_research"] = native_research or {
        "performed": False,
        "web_search_call_count": 0,
        "web_fetch_call_count": 0,
    }
    return plan


def getattr_model_attr(payload: dict[str, Any], key: str) -> Any:
    return payload.get(key)


def _usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    total_tokens = getattr(usage, "total_tokens", None)
    if callable(total_tokens):
        total_tokens = total_tokens()
    details = getattr(usage, "details", {}) or {}
    return {
        "provider_reported": True,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": total_tokens,
        "cache_write_tokens": getattr(usage, "cache_write_tokens", None),
        "cache_read_tokens": getattr(usage, "cache_read_tokens", None),
        "requests": getattr(usage, "requests", None),
        "tool_calls": getattr(usage, "tool_calls", None),
        "details": details,
    }


def _estimated_usage(*, prompt: str, response: str) -> dict[str, Any]:
    prompt_tokens = _rough_token_count(prompt)
    response_tokens = _rough_token_count(response)
    return {
        "provider_reported": False,
        "input_tokens": prompt_tokens,
        "output_tokens": response_tokens,
        "total_tokens": prompt_tokens + response_tokens,
        "estimation_method": "rough_chars_div_4_mixed_cjk",
        "requests": 1,
        "tool_calls": 0,
    }


def _rough_token_count(text: str) -> int:
    if not text:
        return 0
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = max(0, len(text) - cjk_chars)
    return max(1, round(cjk_chars * 1.1 + other_chars / 4))


def _compact_dict(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    return {key: payload[key] for key in list(payload)[:limit]}


def _point_angles(variant: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    raw = variant.get("point_angles")
    if not isinstance(raw, list):
        return result
    for item in raw:
        if isinstance(item, dict):
            result.append({str(k): str(v) for k, v in item.items() if v is not None})
    return result


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _point_sentence(point: dict[str, Any]) -> str:
    layers = "、".join(point.get("sec6_layers", []) or [])
    family = "、".join(point.get("source_families", []) or [])
    parts = []
    if layers:
        parts.append(f"可連到 {layers} 面向")
    if family:
        parts.append(f"來源線索包含 {family}")
    if point.get("observation_value") is not None:
        parts.append(f"觀察價值 {point.get('observation_value')}")
    return "，".join(parts) or "出發前確認此點和路線段落的關係。"


def _distance_km(value: Any) -> str:
    try:
        return f"{float(value) / 1000:.2f} km"
    except (TypeError, ValueError):
        return "距離待確認"


def _image(image: dict[str, Any], *, class_name: str = "") -> str:
    src = _text(image.get("url") or image.get("src"), "")
    alt = _text(image.get("caption") or image.get("alt") or "路線照片", "路線照片")
    if not src:
        return ""
    class_attr = f' class="{_esc(class_name)}"' if class_name else ""
    return f'<img{class_attr} src="{_esc(src)}" alt="{_esc(alt)}" loading="lazy">'


def _is_bad_image_url(url: str) -> bool:
    lowered = url.casefold()
    if any(term in lowered for term in BAD_IMAGE_TERMS):
        return True
    suffix = lowered.split("?", 1)[0].rsplit(".", 1)[-1]
    return suffix in {"svg", "gif", "ico"}


def _visible_text(html_text: str) -> str:
    cleaned = re.sub(r"<script\b.*?</script>", " ", html_text, flags=re.I | re.S)
    cleaned = re.sub(r"<style\b.*?</style>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<svg\b.*?</svg>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _fenced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    collecting = False
    collected: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if collecting:
                candidates.append("\n".join(collected).strip())
                collected = []
                collecting = False
                continue
            if stripped[3:].strip().lower() in {"", "json"}:
                collecting = True
                collected = []
            continue
        if collecting:
            collected.append(line)
    return candidates


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "variant"


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or default


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate five Scout AI route-context briefing variants from the route-context-intelligence skill."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--baseline-html", type=Path, default=None)
    parser.add_argument("--skill-path", type=Path, default=ROOT / DEFAULT_SKILL_REF)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--reference-variants-dir", type=Path, default=None)
    parser.add_argument("--max-reference-similarity", type=float, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--model-max-tokens", type=int, default=16384)
    args = parser.parse_args(argv)

    load_scout_env_files(repo_root=ROOT)
    policy = resolve_model_policy(args.model)
    if policy.missing_credential_env:
        raise SystemExit(
            "missing required model credential env: "
            + ", ".join(policy.missing_credential_env)
        )
    project_root = args.project_root.expanduser().resolve()
    baseline_html = (
        args.baseline_html.expanduser().resolve()
        if args.baseline_html
        else (project_root / DEFAULT_BASELINE_REF).resolve()
    )
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else (project_root / DEFAULT_OUTPUT_DIR).resolve()
    )
    reference_variants_dir = (
        args.reference_variants_dir.expanduser().resolve()
        if args.reference_variants_dir
        else None
    )
    runner = UsageRecordingPydanticAIRunner(
        model_name=args.model,
        model_max_tokens=args.model_max_tokens,
    )
    result = generate_route_context_briefing_variants(
        project_root=project_root,
        baseline_html=baseline_html,
        skill_path=args.skill_path,
        output_dir=output_dir,
        runner=runner,
        timeout_seconds=args.timeout_seconds,
        reference_variants_dir=reference_variants_dir,
        max_reference_similarity=args.max_reference_similarity,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
