from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from assistant_model_config import load_assistant_model_config
from pydantic_ai_runtime_compat import (
    build_chat_model,
    pydantic_agent_runtime_kwargs,
)
from scout_env import load_scout_env_files


ROOT = Path(__file__).resolve().parent
EVIDENCE_SCHEMA_VERSION = "scout.route_context_regeneration_evidence.v1"
EDITORIAL_PLAN_SCHEMA_VERSION = "scout.route_context_editorial_plan.v1"
RECEIPT_SCHEMA_VERSION = "scout.route_context_regeneration_receipt.v1"
DEFAULT_MODEL_CONFIG = ROOT / "configs" / "assistant-models.dashboard-aihat2.json"
DEFAULT_SKILL_PATH = (
    ROOT / ".agents" / "skills" / "scout-route-context-briefing" / "SKILL.md"
)
DEFAULT_TIMEOUT_SECONDS = 240
MAX_EDITORIAL_PLAN_ATTEMPTS = 3
OUTPUT_DIR = Path("outputs/route_context_regeneration")
EVIDENCE_PACKET_REF = OUTPUT_DIR / "evidence_packet.json"
EDITORIAL_PLAN_REF = OUTPUT_DIR / "scout_ai_editorial_plan.json"
RECEIPT_REF = OUTPUT_DIR / "regeneration_receipt.json"
DEFAULT_BRIEFING_REF = Path("outputs/briefings/route_context_briefing.html")

SECTION_IDS = (
    "decision_snapshot",
    "route_identity",
    "reference_itinerary",
    "logistics_and_application",
    "route_atlas",
    "visual_essay",
    "six_context_layers",
    "p2_route_memory",
    "source_ledger",
)
LAYER_IDS = (
    "historical",
    "cultural",
    "natural",
    "terrain",
    "seasonal",
    "observation_point",
)
LAYER_LABELS = {
    "historical": "歷史",
    "cultural": "文化",
    "natural": "自然",
    "terrain": "地形",
    "seasonal": "季節",
    "observation_point": "觀察點",
}
BLOCKED_EDITORIAL_TERMS = (
    "Scout AI",
    "DeepSeek",
    "prompt",
    "模型",
    "compiler",
    "編譯器",
    "workspace",
    "cache",
    "artifact",
    "candidate_only",
    "runtime_safety_truth",
    "JSON",
)


class RouteContextRegenerationError(RuntimeError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSource(_StrictModel):
    source_id: str = Field(min_length=1)
    tier: Literal["P0", "P1", "P2"]
    title: str = Field(min_length=1)
    url: str
    published_at: str | None = None
    checked_at: str

    @field_validator("source_id", "title", "checked_at")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("source text fields must not be empty")
        return text

    @field_validator("url")
    @classmethod
    def _absolute_url(cls, value: str) -> str:
        text = value.strip()
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source url must be an absolute HTTP(S) URL")
        return text


class SourcedBlock(_StrictModel):
    source_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_ids")
    @classmethod
    def _source_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not normalized:
            raise ValueError("source_ids must not be empty")
        return normalized


class RouteIdentity(SourcedBlock):
    bound_track_name: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class CurrentStatus(SourcedBlock):
    operability: Literal["open", "closed", "unknown"]
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ItineraryDay(_StrictModel):
    day: str = Field(pattern=r"^D\d{1,2}$")
    route: str = Field(min_length=1)
    notes: str = Field(min_length=1)


class ReferenceItinerary(SourcedBlock):
    label: str = Field(min_length=1)
    caveat: str = Field(min_length=1)
    days: tuple[ItineraryDay, ...] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def _ordered_unique_days(self) -> Self:
        numbers = [int(day.day[1:]) for day in self.days]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            raise ValueError("reference itinerary days must be unique and ordered")
        return self


class Logistics(SourcedBlock):
    access: str = Field(min_length=1)
    exit: str = Field(min_length=1)
    unresolved: tuple[str, ...] = Field(min_length=1)


class Application(SourcedBlock):
    classification: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    requirements: tuple[str, ...] = Field(min_length=1)


class ContextClaim(SourcedBlock):
    layer: Literal[
        "historical",
        "cultural",
        "natural",
        "terrain",
        "seasonal",
        "observation_point",
    ]
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RegenerationEvidence(_StrictModel):
    schema_version: Literal[EVIDENCE_SCHEMA_VERSION]
    project_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    checked_at: str
    route_identity: RouteIdentity
    current_status: CurrentStatus
    reference_itinerary: ReferenceItinerary
    logistics: Logistics
    application: Application
    context_claims: tuple[ContextClaim, ...] = Field(min_length=1)
    unresolved_items: tuple[str, ...] = Field(min_length=1)
    sources: tuple[EvidenceSource, ...] = Field(min_length=1)

    @field_validator("checked_at")
    @classmethod
    def _checked_at(cls, value: str) -> str:
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("checked_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("checked_at must include timezone")
        return text

    @model_validator(mode="after")
    def _validate_source_graph(self) -> Self:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        known = set(source_ids)
        blocks: tuple[SourcedBlock, ...] = (
            self.route_identity,
            self.current_status,
            self.reference_itinerary,
            self.logistics,
            self.application,
            *self.context_claims,
        )
        for block in blocks:
            unknown = sorted(set(block.source_ids) - known)
            if unknown:
                raise ValueError(f"unknown source_id: {', '.join(unknown)}")
        tiers = {source.source_id: source.tier for source in self.sources}
        if any(tiers[source_id] != "P0" for source_id in self.current_status.source_ids):
            raise ValueError("current_status must be supported only by P0 sources")
        if any(tiers[source_id] != "P0" for source_id in self.application.source_ids):
            raise ValueError("application must be supported only by P0 sources")
        return self


class EditorialPlan(_StrictModel):
    artifact_kind: Literal["scout_ai_route_context_editorial_plan"]
    schema_version: Literal[EDITORIAL_PLAN_SCHEMA_VERSION]
    title: str = Field(min_length=1, max_length=40)
    eyebrow: str = Field(min_length=1, max_length=60)
    subtitle: str = Field(min_length=1, max_length=90)
    section_order: tuple[
        Literal[
            "decision_snapshot",
            "route_identity",
            "reference_itinerary",
            "logistics_and_application",
            "route_atlas",
            "visual_essay",
            "six_context_layers",
            "p2_route_memory",
            "source_ledger",
        ],
        ...,
    ] = Field(min_length=len(SECTION_IDS), max_length=len(SECTION_IDS))
    section_headings: dict[str, str]
    reader_questions: tuple[str, ...] = Field(min_length=3, max_length=4)
    closing_note: str = Field(min_length=1, max_length=60)

    @field_validator(
        "title",
        "eyebrow",
        "subtitle",
        "closing_note",
    )
    @classmethod
    def _visible_copy(cls, value: str) -> str:
        return _validated_editorial_text(value)

    @field_validator("reader_questions")
    @classmethod
    def _questions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_validated_editorial_text(value) for value in values)
        if any(not value.endswith(("？", "?")) for value in cleaned):
            raise ValueError("reader_questions must be phrased as questions")
        return cleaned

    @model_validator(mode="after")
    def _complete_structure(self) -> Self:
        if set(self.section_order) != set(SECTION_IDS):
            raise ValueError("section_order must contain every required section once")
        if set(self.section_headings) != set(SECTION_IDS):
            raise ValueError("section_headings must cover every required section")
        normalized_headings = {
            key: _validated_editorial_text(value)
            for key, value in self.section_headings.items()
        }
        object.__setattr__(self, "section_headings", normalized_headings)
        return self


ModelCaller = Callable[..., dict[str, object]]


def regenerate_route_context_briefing(
    *,
    project_root: Path | str,
    evidence_path: Path | str,
    model_config_path: Path | str = DEFAULT_MODEL_CONFIG,
    skill_path: Path | str = DEFAULT_SKILL_PATH,
    model_name: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    env_file: Path | str | None = None,
    model_caller: ModelCaller | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise RouteContextRegenerationError(f"project root not found: {root}")
    project = _load_json(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)

    evidence_file = Path(evidence_path).expanduser().resolve()
    if not evidence_file.is_file():
        raise RouteContextRegenerationError(
            f"regeneration evidence not found: {evidence_file}"
        )
    try:
        evidence = RegenerationEvidence.model_validate(_load_json(evidence_file))
    except Exception as exc:
        raise RouteContextRegenerationError(
            f"regeneration evidence is invalid: {exc}"
        ) from exc
    if evidence.project_id != project_id:
        raise RouteContextRegenerationError(
            "regeneration evidence belongs to another project"
        )

    skill_file = Path(skill_path).expanduser().resolve()
    if not skill_file.is_file():
        raise RouteContextRegenerationError(f"route-context skill not found: {skill_file}")
    skill_text = skill_file.read_text(encoding="utf-8")

    config_file = Path(model_config_path).expanduser().resolve()
    if not config_file.is_file():
        raise RouteContextRegenerationError(f"model config not found: {config_file}")
    model_config = load_assistant_model_config(config_file)
    profile = model_config.cloud_model
    selected_model = (model_name or profile.model_name).strip()
    if not selected_model:
        raise RouteContextRegenerationError("cloud model name is empty")

    workspace = _load_workspace_snapshot(root, project)
    base_prompt = _build_prompt(
        evidence=evidence,
        workspace=workspace,
        skill_text=skill_text,
    )
    base_prompt_sha256 = _sha256_text(base_prompt)
    api_key = ""
    if model_caller is None:
        persistent_env = (
            Path(env_file).expanduser().resolve() if env_file is not None else None
        )
        load_scout_env_files(repo_root=ROOT, persistent_env_file=persistent_env)
        token_env_var = profile.token_env_var or "OPENROUTER_API_KEY"
        api_key = os.getenv(token_env_var)
        if not api_key:
            raise RouteContextRegenerationError(
                f"{token_env_var} is required for Scout AI cloud regeneration"
            )

    attempts: list[dict[str, Any]] = []
    call_results: list[dict[str, object]] = []
    active_prompt = base_prompt
    call_result: dict[str, object] = {}
    plan: EditorialPlan | None = None
    for attempt_number in range(1, MAX_EDITORIAL_PLAN_ATTEMPTS + 1):
        if model_caller is None:
            call_result = _call_live_model(
                prompt=active_prompt,
                model_name=selected_model,
                base_url=profile.resolved_base_url(),
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
        else:
            call_result = model_caller(
                prompt=active_prompt,
                model_name=selected_model,
                base_url=profile.resolved_base_url(),
                timeout_seconds=timeout_seconds,
            )
        call_results.append(call_result)
        prompt_sha256 = _sha256_text(active_prompt)
        try:
            candidate_plan = EditorialPlan.model_validate(call_result.get("plan"))
            _validate_editorial_plan_for_workspace(
                candidate_plan,
                workspace,
                evidence,
            )
        except Exception as exc:
            validation_error = _editorial_validation_error(exc)
            attempts.append(
                _model_attempt_record(
                    attempt_number=attempt_number,
                    prompt_sha256=prompt_sha256,
                    call_result=call_result,
                    status="rejected",
                    validation_error=validation_error,
                )
            )
            if attempt_number >= MAX_EDITORIAL_PLAN_ATTEMPTS:
                raise RouteContextRegenerationError(
                    "Scout AI editorial plan failed its quality contract after "
                    f"{MAX_EDITORIAL_PLAN_ATTEMPTS} attempts: "
                    f"{validation_error}"
                ) from exc
            active_prompt = _build_repair_prompt(
                base_prompt=base_prompt,
                rejected_plan=call_result.get("plan"),
                validation_error=validation_error,
                next_attempt=attempt_number + 1,
            )
            continue
        plan = candidate_plan
        attempts.append(
            _model_attempt_record(
                attempt_number=attempt_number,
                prompt_sha256=prompt_sha256,
                call_result=call_result,
                status="accepted",
            )
        )
        break

    if plan is None:
        raise RouteContextRegenerationError("Scout AI editorial plan was not accepted")
    prompt = active_prompt
    prompt_sha256 = _sha256_text(prompt)
    aggregate_usage = _aggregate_usage(call_results)

    generated_at = generated_at or _utc_now()
    briefing_ref = Path(
        str(project.get("route_context_briefing_ref") or DEFAULT_BRIEFING_REF.as_posix())
    )
    briefing_path = _safe_project_path(root, briefing_ref)
    baseline_bytes = briefing_path.read_bytes() if briefing_path.is_file() else b""
    baseline_exists = briefing_path.is_file()
    baseline_sha256 = hashlib.sha256(baseline_bytes).hexdigest()
    evidence_sha256 = _sha256_file(evidence_file)
    skill_sha256 = _sha256_file(skill_file)
    html_text = render_route_context_briefing(
        evidence=evidence,
        plan=plan,
        workspace=workspace,
        generated_at=generated_at,
    )
    _validate_rendered_html(html_text, evidence=evidence)
    briefing_sha256 = _sha256_text(html_text)

    archive_ref = _archive_ref(generated_at) if baseline_exists else None
    if archive_ref is not None:
        archive_path = _safe_project_path(root, archive_ref)
        _write_bytes(archive_path, baseline_bytes)

    model_record = {
        "artifact_kind": "scout_ai_route_context_editorial_plan_record",
        "schema_version": EDITORIAL_PLAN_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "model": selected_model,
        "provider": _provider_name(profile.resolved_base_url(), call_result),
        "prompt_sha256": prompt_sha256,
        "base_prompt_sha256": base_prompt_sha256,
        "evidence_sha256": evidence_sha256,
        "skill_ref": str(skill_file),
        "skill_sha256": skill_sha256,
        "plan": plan.model_dump(mode="json"),
        "usage": aggregate_usage,
        "response_metadata": _string_mapping(call_result.get("response_metadata")),
        "attempts": attempts,
        "editorial_contract": _editorial_contract_receipt(evidence),
        "boundary": _boundary(),
    }
    evidence_packet = {
        "artifact_kind": "route_context_regeneration_evidence_packet",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "project_id": project_id,
        "evidence_sha256": evidence_sha256,
        "source_file": str(evidence_file),
        "evidence": evidence.model_dump(mode="json"),
        "workspace_snapshot": workspace,
        "boundary": _boundary(),
    }
    receipt = {
        "artifact_kind": "route_context_regeneration_receipt",
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "project_id": project_id,
        "status": "completed",
        "generated_at": generated_at,
        "model": selected_model,
        "provider": model_record["provider"],
        "skill_sha256": skill_sha256,
        "prompt_sha256": prompt_sha256,
        "base_prompt_sha256": base_prompt_sha256,
        "evidence_sha256": evidence_sha256,
        "baseline_sha256": baseline_sha256,
        "briefing_sha256": briefing_sha256,
        "briefing_ref": briefing_ref.as_posix(),
        "archive_ref": archive_ref.as_posix() if archive_ref is not None else None,
        "evidence_packet_ref": EVIDENCE_PACKET_REF.as_posix(),
        "editorial_plan_ref": EDITORIAL_PLAN_REF.as_posix(),
        "model_usage": model_record["usage"],
        "model_request_count": len(attempts),
        "editorial_contract": model_record["editorial_contract"],
        "boundary": _boundary(),
    }

    _write_json(_safe_project_path(root, EVIDENCE_PACKET_REF), evidence_packet)
    _write_json(_safe_project_path(root, EDITORIAL_PLAN_REF), model_record)
    _write_text(briefing_path, html_text)
    _write_json(_safe_project_path(root, RECEIPT_REF), receipt)
    return {
        "status": "completed",
        "project_id": project_id,
        "model": selected_model,
        "provider": model_record["provider"],
        "briefing_ref": briefing_ref.as_posix(),
        "archive_ref": archive_ref.as_posix() if archive_ref is not None else None,
        "evidence_packet_ref": EVIDENCE_PACKET_REF.as_posix(),
        "editorial_plan_ref": EDITORIAL_PLAN_REF.as_posix(),
        "receipt_ref": RECEIPT_REF.as_posix(),
        "prompt_sha256": prompt_sha256,
        "base_prompt_sha256": base_prompt_sha256,
        "evidence_sha256": evidence_sha256,
        "baseline_sha256": baseline_sha256,
        "briefing_sha256": briefing_sha256,
        "usage": model_record["usage"],
        "model_request_count": len(attempts),
        "editorial_contract": model_record["editorial_contract"],
        "boundary": _boundary(),
    }


def render_route_context_briefing(
    *,
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    workspace: dict[str, Any],
    generated_at: str,
) -> str:
    sources = {source.source_id: source for source in evidence.sources}
    section_renderers: dict[str, Callable[[], str]] = {
        "decision_snapshot": lambda: _decision_snapshot(
            evidence, plan, sources, workspace
        ),
        "route_identity": lambda: _route_identity(evidence, plan, sources),
        "reference_itinerary": lambda: _reference_itinerary(
            evidence, plan, sources
        ),
        "logistics_and_application": lambda: _logistics_and_application(
            evidence, plan, sources
        ),
        "route_atlas": lambda: _route_atlas(evidence, plan, workspace),
        "visual_essay": lambda: _visual_essay(plan, workspace),
        "six_context_layers": lambda: _six_context_layers(
            evidence, plan, sources, workspace
        ),
        "p2_route_memory": lambda: _p2_route_memory(plan, workspace),
        "source_ledger": lambda: _source_ledger(evidence, plan, workspace),
    }
    sections = "\n".join(section_renderers[section_id]() for section_id in plan.section_order)
    hero_image = _hero_image(workspace)
    hero_media = (
        '<figure class="hero-media">'
        f'<img src="{_h(hero_image.get("url"))}" '
        f'alt="{_h(hero_image.get("alt") or hero_image.get("caption") or "")}">'
        f'<figcaption>{_h(hero_image.get("caption") or hero_image.get("alt") or "")}</figcaption>'
        "</figure>"
        if hero_image
        else ""
    )
    nav = "".join(
        f'<a href="#{_h(section_id)}">{_h(plan.section_headings[section_id])}</a>'
        for section_id in plan.section_order
    )
    generated_date = generated_at.split("T", 1)[0]
    closed_route = evidence.current_status.operability == "closed"
    document_mode = (
        "未開放路線的脈絡導覽"
        if closed_route
        else "可追溯的行前路線導覽"
    )
    status_banner = (
        """
        <aside class="hero-status" role="note">
          <strong>目前未開放｜不是可直接套用的出發方案</strong>
          <p>本頁只用來讀懂路線、歷史實走與未來查核順序。官方恢復「其他路線」以前，不建立可執行的宿點、接駁或申請方案。</p>
        </aside>
        """
        if closed_route
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="generator" content="Scout deterministic route-context renderer">
  <title>{_h(plan.title)}｜{_h(document_mode)}</title>
  <style>{_css()}</style>
</head>
<body>
  <header class="hero">
    <div class="hero-copy">
      <p class="eyebrow">{_h(plan.eyebrow)}</p>
      <h1>{_h(plan.title)}</h1>
      <p class="subtitle">{_h(plan.subtitle)}</p>
      <p class="document-mode">{_h(document_mode)}</p>
      {status_banner}
      <div class="hero-pills">
        <span>綁定軌跡：{_h(evidence.route_identity.bound_track_name)}</span>
        <span>{_h(evidence.route_identity.direction)}</span>
        <span>證據查核：{_h(evidence.checked_at[:10])}</span>
      </div>
    </div>
    {hero_media}
  </header>
  <nav aria-label="本頁章節"><div>{nav}</div></nav>
  <main>{sections}</main>
  <footer>
    <strong>{_h(plan.closing_note)}</strong>
    <p>本頁整理路線研究、歷史實走與申請查核；在官方恢復與全部缺口重查前，不是可執行行程、通行證明、現場判斷或出發核准。產製日期：{_h(generated_date)}</p>
  </footer>
</body>
</html>
"""


def _decision_snapshot(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    sources: dict[str, EvidenceSource],
    workspace: dict[str, Any],
) -> str:
    route = workspace["route_summary"]
    questions = "".join(f"<li>{_h(question)}</li>" for question in plan.reader_questions)
    unresolved = "".join(f"<li>{_h(item)}</li>" for item in evidence.unresolved_items)
    hard_gate = (
        """
        <aside class="hard-gate">
          <span>第 0 道閘門</span>
          <strong>先等官方恢復清代東段所屬的「其他路線」</strong>
          <p>這道閘門未通過以前，不把舊宿點、舊接駁或九日節奏編成出發方案。恢復後仍須重新查證路況、合法宿營、接駁、天氣與完整登山計畫。</p>
        </aside>
        """
        if evidence.current_status.operability == "closed"
        else ""
    )
    return _section(
        "decision_snapshot",
        plan.section_headings["decision_snapshot"],
        f"""
        <div class="decision-grid">
          <article class="status-card blocked">
            <span class="card-kicker">{_h(evidence.current_status.label)}</span>
            <h3>{_h(evidence.current_status.summary)}</h3>
            <p>{_h(evidence.current_status.reason)}</p>
            {_source_chips(evidence.current_status.source_ids, sources)}
          </article>
          <article class="metric-card">
            <span>軌跡尺度</span>
            <strong>{_format_km(route.get("distance_m"))}</strong>
            <p>這是目前綁定軌跡的重算距離，不是官方公告里程。</p>
          </article>
          <article class="metric-card">
            <span>高度範圍</span>
            <strong>{_format_elevation_range(route)}</strong>
            <p>由綁定軌跡摘要計算，只用來理解整體地形尺度。</p>
          </article>
          <article class="metric-card">
            <span>歷史參考</span>
            <strong>{len(evidence.reference_itinerary.days)} 天</strong>
            <p>{_h(evidence.reference_itinerary.caveat)}</p>
          </article>
        </div>
        {hard_gate}
        <div class="reader-grid">
          <article>
            <p class="section-kicker">帶著這些問題讀</p>
            <ol>{questions}</ol>
          </article>
          <article>
            <p class="section-kicker">仍未解決</p>
            <ul>{unresolved}</ul>
          </article>
        </div>
        """,
    )


def _route_identity(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    sources: dict[str, EvidenceSource],
) -> str:
    history_claims = [
        claim for claim in evidence.context_claims if claim.layer in {"historical", "cultural"}
    ]
    claim_cards = "".join(
        f'<article class="story-card"><span>{_h(LAYER_LABELS[claim.layer])}</span>'
        f"<h3>{_h(claim.title)}</h3><p>{_h(claim.text)}</p>"
        f"{_source_chips(claim.source_ids, sources)}</article>"
        for claim in history_claims
    )
    return _section(
        "route_identity",
        plan.section_headings["route_identity"],
        f"""
        <div class="identity-board">
          <div>
            <p class="section-kicker">名稱與資料綁定</p>
            <p class="lead">{_h(evidence.route_identity.explanation)}</p>
            <dl>
              <div><dt>導覽名稱</dt><dd>{_h(evidence.display_name)}</dd></div>
              <div><dt>軌跡名稱</dt><dd>{_h(evidence.route_identity.bound_track_name)}</dd></div>
              <div><dt>方向</dt><dd>{_h(evidence.route_identity.direction)}</dd></div>
            </dl>
            {_source_chips(evidence.route_identity.source_ids, sources)}
          </div>
          <aside>
            <strong>不要混成同一條維護步道</strong>
            <p>本頁會分開呈現清代古道、日治越道路、現行申請分類與 2020 實走紀錄；名稱接近，不代表路線、路況或宿點可以互換。</p>
          </aside>
        </div>
        <div class="story-grid">{claim_cards}</div>
        """,
    )


def _reference_itinerary(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    sources: dict[str, EvidenceSource],
) -> str:
    cards = "".join(
        f'<article class="day-card"><span>{_h(day.day)}</span>'
        f"<div><h3>{_h(day.route)}</h3><p>{_h(day.notes)}</p></div></article>"
        for day in evidence.reference_itinerary.days
    )
    return _section(
        "reference_itinerary",
        plan.section_headings["reference_itinerary"],
        f"""
        <div class="section-intro">
          <div>
            <p class="section-kicker">有來源的歷史實走</p>
            <p class="lead">{_h(evidence.reference_itinerary.label)}</p>
          </div>
          <p class="caveat">{_h(evidence.reference_itinerary.caveat)} 這組 D1–D{len(evidence.reference_itinerary.days)} 只用來理解當年路線順序，不得直接套用為今日規劃模板；不同季節的水量、植被、日照與天氣都必須重新評估。</p>
        </div>
        <div class="day-list">{cards}</div>
        <div class="source-line">{_source_chips(evidence.reference_itinerary.source_ids, sources)}</div>
        """,
    )


def _logistics_and_application(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    sources: dict[str, EvidenceSource],
) -> str:
    unresolved = "".join(
        f"<li>{_h(item)}</li>" for item in evidence.logistics.unresolved
    )
    requirements = "".join(
        f"<li>{_h(item)}</li>" for item in evidence.application.requirements
    )
    flow = (
        """
        <div class="flow" aria-label="官方重開後的查核順序">
          <span><b>0</b>等待官方恢復「其他路線」</span>
          <span><b>1</b>重查路況、渡溪與合法宿營</span>
          <span><b>2</b>確認接駁、隊伍、留守與撤退</span>
          <span><b>3</b>查天氣後依規則送完整計畫</span>
        </div>
        """
        if evidence.current_status.operability == "closed"
        else """
        <div class="flow" aria-label="出發前查核順序">
          <span><b>1</b>確認最新官方狀態</span>
          <span><b>2</b>重建逐日宿營與撤退計畫</span>
          <span><b>3</b>確認接駁、隊伍與留守</span>
          <span><b>4</b>依其他路線規則送件</span>
        </div>
        """
    )
    return _section(
        "logistics_and_application",
        plan.section_headings["logistics_and_application"],
        f"""
        <div class="logistics-grid">
          <article>
            <span class="card-kicker">2020 參考隊伍的進出方式</span>
            <h3>接駁只能當歷史線索</h3>
            <p><b>進場：</b>{_h(evidence.logistics.access)}</p>
            <p><b>退場：</b>{_h(evidence.logistics.exit)}</p>
            <ul>{unresolved}</ul>
            {_source_chips(evidence.logistics.source_ids, sources)}
          </article>
          <article class="application-card">
            <span class="card-kicker">目前申請分類</span>
            <h3>{_h(evidence.application.classification)}</h3>
            <p>{_h(evidence.application.summary)}</p>
            <ol>{requirements}</ol>
            {_source_chips(evidence.application.source_ids, sources)}
          </article>
        </div>
        {flow}
        """,
    )


def _route_atlas(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    workspace: dict[str, Any],
) -> str:
    route = workspace["route_summary"]
    points = sorted(
        [point for point in workspace["points"] if point.get("source_tier") == "P1"],
        key=lambda point: float(point.get("distance_m") or 0),
    )
    point_cards = "".join(
        '<article class="point-card">'
        f'<span>{_format_km(point.get("distance_m"))}</span>'
        f"<h3>{_h(_point_label(point))}</h3>"
        f"<p>{_h(_context_label(point.get('context_kind')))}</p>"
        "</article>"
        for point in points[:10]
    )
    return _section(
        "route_atlas",
        plan.section_headings["route_atlas"],
        f"""
        <div class="atlas-summary">
          <article><span>綁定距離</span><b>{_format_km(route.get("distance_m"))}</b></article>
          <article><span>最低高度</span><b>{_format_m(route.get("elevation_min_m"))}</b></article>
          <article><span>最高高度</span><b>{_format_m(route.get("elevation_max_m"))}</b></article>
          <article><span>軌跡點</span><b>{_h(route.get("point_count") or "—")}</b></article>
        </div>
        <p class="lead">這些節點來自已綁定的路線證據，里程只代表在目前軌跡上的投影位置；不能自動解讀成合法宿點、補水點或今日可通行位置。</p>
        <div class="point-rail">{point_cards}</div>
        """,
    )


def _visual_essay(plan: EditorialPlan, workspace: dict[str, Any]) -> str:
    images = workspace["images"][:6]
    if not images:
        gallery = (
            '<div class="empty-state">目前沒有已核對來源的路線圖像；'
            "保留缺口，不以示意圖冒充現地照片。</div>"
        )
    else:
        gallery = '<div class="visual-grid">' + "".join(
            '<figure>'
            f'<img loading="lazy" src="{_h(image.get("url"))}" '
            f'alt="{_h(image.get("alt") or image.get("caption") or "")}">'
            f'<figcaption><span>{_h(image.get("source_tier") or "來源")}</span>'
            f'{_h(image.get("caption") or image.get("alt") or "路線圖像")}</figcaption>'
            "</figure>"
            for image in images
            if image.get("url")
        ) + "</div>"
    return _section(
        "visual_essay",
        plan.section_headings["visual_essay"],
        f"""
        <p class="lead">圖像用來理解道路歷史、文化地景與路線方向；沒有點位錨定的圖片，不對應到特定里程或今天的現地狀態。</p>
        {gallery}
        """,
    )


def _six_context_layers(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    sources: dict[str, EvidenceSource],
    workspace: dict[str, Any],
) -> str:
    cards: list[str] = []
    for layer in LAYER_IDS:
        claims = [claim for claim in evidence.context_claims if claim.layer == layer]
        point_labels = [
            _point_label(point)
            for point in workspace["points"]
            if layer in _string_list(point.get("sec6_layers"))
            and point.get("source_tier") == "P1"
        ][:5]
        claim_html = "".join(
            f"<h4>{_h(claim.title)}</h4><p>{_h(claim.text)}</p>"
            f"{_source_chips(claim.source_ids, sources)}"
            for claim in claims
        )
        if not claim_html:
            claim_html = (
                "<p>目前沒有足夠的公開證據形成路線結論；"
                "未來重查時仍需補入可追溯資料。</p>"
            )
        point_text = (
            "可對照節點：" + "、".join(point_labels)
            if point_labels
            else "目前沒有通過品質門檻的具名節點。"
        )
        cards.append(
            f'<article class="layer-card layer-{_h(layer)}">'
            f'<span>{_h(LAYER_LABELS[layer])}</span>'
            f"{claim_html}<small>{_h(point_text)}</small></article>"
        )
    return _section(
        "six_context_layers",
        plan.section_headings["six_context_layers"],
        """
        <p class="lead">六層不是六份資料表，而是六個閱讀角度：先看有來源的結論，再看哪些節點仍需人工查證。</p>
        <div class="layer-grid">""" + "".join(cards) + "</div>",
    )


def _p2_route_memory(plan: EditorialPlan, workspace: dict[str, Any]) -> str:
    points = [
        point for point in workspace["points"] if point.get("source_tier") == "P2"
    ]
    labels = [
        _point_label(point)
        for point in points
        if _point_label(point)
    ][:12]
    chips = "".join(f"<span>{_h(label)}</span>" for label in labels)
    return _section(
        "p2_route_memory",
        plan.section_headings["p2_route_memory"],
        f"""
        <div class="p2-board">
          <div>
            <strong>{len(points)}</strong>
            <span>筆隊伍／軌跡線索</span>
          </div>
          <p>這一層保留參考 GPX、里程標籤與隊伍記錄，幫助下一次查證；它不能覆蓋官方公告，也不能單獨證明宿點、路況或可通行性。</p>
        </div>
        <div class="memory-chips">{chips}</div>
        """,
    )


def _source_ledger(
    evidence: RegenerationEvidence,
    plan: EditorialPlan,
    workspace: dict[str, Any],
) -> str:
    rows = "".join(
        "<tr>"
        f'<td><span class="tier tier-{_h(source.tier.casefold())}">{_h(source.tier)}</span></td>'
        f'<td><a href="{_h(source.url)}" rel="noreferrer">{_h(source.title)}</a></td>'
        f"<td>{_h(source.published_at or '未標示')}</td>"
        f"<td>{_h(source.checked_at)}</td>"
        "</tr>"
        for source in evidence.sources
    )
    counts = {
        tier: sum(1 for source in evidence.sources if source.tier == tier)
        for tier in ("P0", "P1", "P2")
    }
    workspace_p2_count = int(
        (workspace.get("counts") or {}).get("p2_point_count") or 0
    )
    p2_count = max(counts["P2"], workspace_p2_count)
    p2_note = (
        "<p>本表只列可點回的公開來源；"
        f"P2 的 {p2_count} 筆專案內路線線索保留在上一節，"
        "不冒充公開來源網址。</p>"
        if p2_count
        else ""
    )
    return _section(
        "source_ledger",
        plan.section_headings["source_ledger"],
        f"""
        <div class="source-summary">
          <span><b>{counts["P0"]}</b>P0 官方</span>
          <span><b>{counts["P1"]}</b>P1 延伸</span>
          <span><b>{p2_count}</b>P2 路線線索</span>
        </div>
        {p2_note}
        <div class="table-wrap">
          <table>
            <thead><tr><th>層級</th><th>來源</th><th>發布</th><th>本次查核</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        <aside class="source-boundary">
          <b>閱讀規則</b>
          <p>P0 支撐公告、申請與官方歷史；P1 提供實走與 GPX 參考；P2 只保存隊伍線索。舊紀錄不能自動變成現況。</p>
        </aside>
        """,
    )


def _section(section_id: str, heading: str, body: str) -> str:
    return (
        f'<section id="{_h(section_id)}">'
        '<div class="section-heading">'
        f'<span>{SECTION_IDS.index(section_id) + 1:02d}</span>'
        f"<h2>{_h(heading)}</h2>"
        "</div>"
        f"{body}</section>"
    )


def _source_chips(
    source_ids: tuple[str, ...],
    sources: dict[str, EvidenceSource],
) -> str:
    return '<div class="source-chips">' + "".join(
        f'<a href="{_h(sources[source_id].url)}" rel="noreferrer">'
        f'{_h(sources[source_id].tier)} · {_h(sources[source_id].title)}</a>'
        for source_id in source_ids
    ) + "</div>"


def _load_workspace_snapshot(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    route_summary_ref = Path(
        str(project.get("route_summary_ref") or "normalized/routes/route_summary.json")
    )
    points_ref = Path(
        str(
            project.get("route_context_points_ref")
            or "candidates/route_context_points.json"
        )
    )
    media_ref = Path(
        str(
            project.get("route_context_media_manifest_ref")
            or "normalized/context/route_context/media_manifest.json"
        )
    )
    route_summary = _load_json(_safe_project_path(project_root, route_summary_ref))
    points_payload = _load_json(_safe_project_path(project_root, points_ref))
    media_payload = _load_json(_safe_project_path(project_root, media_ref))
    points = (
        points_payload
        if isinstance(points_payload, list)
        else points_payload.get("points")
        or points_payload.get("route_context_points")
        or []
    )
    images = (
        media_payload.get("images")
        or media_payload.get("gallery_images")
        or media_payload.get("media")
        or []
    )
    return {
        "project_id": str(
            project.get("project_id") or project.get("id") or project_root.name
        ),
        "project_route_name": project.get("route_name") or project.get("name"),
        "route_summary": route_summary,
        "points": [point for point in points if isinstance(point, dict)],
        "images": [image for image in images if isinstance(image, dict)],
        "counts": {
            "point_count": len(points),
            "p1_point_count": sum(
                1
                for point in points
                if isinstance(point, dict) and point.get("source_tier") == "P1"
            ),
            "p2_point_count": sum(
                1
                for point in points
                if isinstance(point, dict) and point.get("source_tier") == "P2"
            ),
            "image_count": len(images),
            "p0_image_count": sum(
                1
                for image in images
                if isinstance(image, dict) and image.get("source_tier") == "P0"
            ),
            "p1_image_count": sum(
                1
                for image in images
                if isinstance(image, dict) and image.get("source_tier") == "P1"
            ),
            "p2_image_count": sum(
                1
                for image in images
                if isinstance(image, dict) and image.get("source_tier") == "P2"
            ),
        },
    }


def _build_prompt(
    *,
    evidence: RegenerationEvidence,
    workspace: dict[str, Any],
    skill_text: str,
) -> str:
    closed_route_contract = (
        {
            "decision_heading": (
                "must explicitly state that the route is currently closed or cannot "
                "be used as a ready-to-depart itinerary"
            ),
            "reference_itinerary_heading": (
                "must state that the old trip is historical/reference material and "
                "not a current itinerary"
            ),
            "reader_question_coverage": [
                "current official opening or operability",
                "route identity or historical alignment",
                "whether the old trip reflects current conditions",
                "which route, lodging, or transport gaps still require rechecking",
            ],
            "closing_note": (
                "must mention both official reopening and rechecking route/logistics "
                "before departure planning"
            ),
            "human_facing_heading": (
                "p2_route_memory must use reader-facing language such as 隊伍回顧與軌跡線索, "
                "not the internal label P2路線記憶"
            ),
        }
        if evidence.current_status.operability == "closed"
        else None
    )
    payload = {
        "evidence_packet": evidence.model_dump(mode="json"),
        "workspace_summary": {
            "project_id": workspace["project_id"],
            "project_route_name": workspace["project_route_name"],
            "route_summary": workspace["route_summary"],
            "counts": workspace["counts"],
        },
        "required_section_ids": list(SECTION_IDS),
        "blocked_visible_terms": list(BLOCKED_EDITORIAL_TERMS),
        "closed_route_editorial_contract": closed_route_contract,
        "skill_contract": skill_text,
    }
    return (
        "你是 Scout 路線脈絡編輯。請依 route-context briefing skill 與 evidence_packet，"
        "只產生一份繁體中文的編輯計畫。你不寫 HTML，也不重述或改寫數字、狀態、"
        "日期、行程、申請規則與地名；這些事實將由確定性程式從 evidence_packet "
        "逐欄編譯。你的任務只限於標題、章節標題、閱讀順序、讀者提問與收束語。\n"
        "section_order 與 section_headings 必須各自完整涵蓋 required_section_ids，"
        "不得新增或省略。可見文字不得出現 blocked_visible_terms。"
        "title 必須逐字等於 evidence_packet.display_name，不得改名、加副標或縮寫。"
        "decision_snapshot 必須排第一。若目前未開放，章節標題不能只寫『狀態先於行程』，"
        "而要明說『目前未開放』或『不可直接成行』。舊實走章節要明說只作歷史參考。"
        "reader_questions 必須合計涵蓋目前官方狀態、路線身分或歷史差異、舊紀錄是否代表"
        "現況，以及哪些路況／宿點／接駁缺口仍待重查。closing_note 必須同時寫出官方"
        "重開與重查路況或接駁，不能只確認申請恢復。p2_route_memory 應使用一般讀者"
        "看得懂的隊伍回顧／軌跡線索用語，不得直接以 P2路線記憶 作章名。"
        "若 workspace_summary 顯示沒有 P2 圖片，visual_essay 的章節名稱必須"
        "明確稱為歷史、官方或參考圖像，不得稱為行程照片、實走照片或現地照片。"
        "不要做出出發核准、通行判斷、安全結論或資料外推。\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _build_repair_prompt(
    *,
    base_prompt: str,
    rejected_plan: object,
    validation_error: str,
    next_attempt: int,
) -> str:
    repair_packet = {
        "attempt": next_attempt,
        "rejected_plan": rejected_plan,
        "deterministic_validation_error": validation_error,
    }
    return (
        base_prompt
        + "\n\n上一版未通過 deterministic closed-route editorial contract。"
        "請只修正列出的問題，重新輸出完整結構；不得刪除章節、改寫證據事實或降低"
        "未開放與待查缺口的醒目程度。\n"
        + json.dumps(repair_packet, ensure_ascii=False, sort_keys=True)
    )


def _call_live_model(
    *,
    prompt: str,
    model_name: str,
    base_url: str | None,
    api_key: str,
    timeout_seconds: int,
) -> dict[str, object]:
    from pydantic_ai import Agent

    model = build_chat_model(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
    )
    agent = Agent(
        model,
        output_type=EditorialPlan,
        instructions=(
            "Return only the requested structured editorial plan. "
            "Do not write HTML and do not invent route facts."
        ),
        **pydantic_agent_runtime_kwargs(),
    )
    try:
        result = agent.run_sync(
            prompt,
            model_settings={
                "temperature": 0,
                "timeout": float(max(1, timeout_seconds - 1)),
            },
        )
    except Exception as exc:
        raise RouteContextRegenerationError(
            "Scout AI cloud regeneration failed: "
            + _redact_error(str(exc), api_key)
        ) from exc
    return {
        "plan": result.output.model_dump(mode="json"),
        "usage": _serialize_usage(result),
        "response_metadata": _serialize_response_metadata(result),
    }


def _validated_editorial_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        raise ValueError("editorial copy must not be empty")
    folded = text.casefold()
    blocked = [term for term in BLOCKED_EDITORIAL_TERMS if term.casefold() in folded]
    if blocked:
        raise ValueError(
            "editorial copy contains blocked internal terms: " + ", ".join(blocked)
        )
    if "http://" in folded or "https://" in folded:
        raise ValueError("editorial copy must not contain URLs")
    return text


def _validate_editorial_plan_for_workspace(
    plan: EditorialPlan,
    workspace: dict[str, Any],
    evidence: RegenerationEvidence,
) -> None:
    if plan.title != evidence.display_name:
        raise RouteContextRegenerationError(
            "editorial title must exactly match evidence display_name"
        )
    counts = workspace.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    if int(counts.get("p2_image_count") or 0) <= 0:
        visual_heading = plan.section_headings["visual_essay"]
        misleading_terms = ("行程照片", "實走照片", "現地照片")
        found = [term for term in misleading_terms if term in visual_heading]
        if found:
            raise RouteContextRegenerationError(
                "visual_essay heading mislabels non-P2 imagery: "
                + ", ".join(found)
            )
    if evidence.current_status.operability != "closed":
        return

    violations: list[str] = []
    if plan.section_order[0] != "decision_snapshot":
        violations.append("decision_snapshot must be the first section")

    decision_heading = plan.section_headings["decision_snapshot"]
    if not _contains_any(
        decision_heading,
        ("未開放", "不可直接", "不能直接", "不可成行", "不能成行", "暫勿成行"),
    ):
        violations.append(
            "decision heading must explicitly say currently closed or not directly actionable"
        )

    identity_heading = plan.section_headings["route_identity"]
    if not _contains_any(
        identity_heading,
        ("身分", "哪一條", "分清", "清代", "日治", "東段", "綁定", "路線"),
    ):
        violations.append("route identity heading must help distinguish the bound route")

    itinerary_heading = plan.section_headings["reference_itinerary"]
    if not (
        _contains_any(itinerary_heading, ("舊", "歷史", "實走", "紀錄"))
        and _contains_any(
            itinerary_heading,
            ("參考", "只作", "僅供", "不能", "不得", "不等於", "不是今日"),
        )
    ):
        violations.append(
            "reference itinerary heading must mark the old trip as historical/reference only"
        )

    p2_heading = plan.section_headings["p2_route_memory"]
    if "P2" in p2_heading.upper():
        violations.append("p2_route_memory heading must use reader-facing wording")

    questions = plan.reader_questions
    joined_questions = " ".join(questions)
    if not _contains_any(
        joined_questions,
        ("官方", "開放", "未開放", "成行", "申請", "目前", "現在"),
    ):
        violations.append("reader questions must cover the current official status")
    if not _contains_any(
        joined_questions,
        ("清代", "日治", "東段", "身分", "哪一條", "不同", "差異", "歷史", "文化"),
    ):
        violations.append("reader questions must cover route identity or historical context")
    if not any(
        _contains_any(question, ("舊", "實走", "紀錄", "行程", "參考"))
        and _contains_any(
            question,
            ("今日", "現在", "現況", "沿用", "代表", "證明", "不能", "可不可以"),
        )
        for question in questions
    ):
        violations.append(
            "a reader question must test whether the old trip represents current conditions"
        )
    if not any(
        _contains_any(
            question,
            ("重查", "查證", "待查", "未確認", "缺口", "仍需確認", "哪些資料"),
        )
        for question in questions
    ):
        violations.append("reader questions must expose a concrete recheck gap")

    if not _contains_any(
        plan.closing_note,
        ("恢復", "重開", "重新開放", "開放後"),
    ):
        violations.append("closing note must retain the official reopening gate")
    if not (
        _contains_any(plan.closing_note, ("重查", "查證", "再確認"))
        and _contains_any(
            plan.closing_note,
            ("路況", "接駁", "宿點", "缺口", "資料", "營地"),
        )
    ):
        violations.append("closing note must require route or logistics rechecking")

    if violations:
        raise RouteContextRegenerationError(
            "closed-route editorial contract failed: " + "; ".join(violations)
        )


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return any(term.casefold() in folded for term in terms)


def _editorial_contract_receipt(
    evidence: RegenerationEvidence,
) -> dict[str, object]:
    closed_route = evidence.current_status.operability == "closed"
    return {
        "status": "PASS",
        "mode": (
            "closed_route_non_regression"
            if closed_route
            else "standard_route_editorial"
        ),
        "checks": (
            [
                "title_binding",
                "visual_evidence_label",
                "decision_first",
                "route_identity",
                "historical_itinerary_boundary",
                "reader_question_coverage",
                "official_reopening_and_recheck_closing",
                "human_facing_section_copy",
            ]
            if closed_route
            else ["title_binding", "visual_evidence_label"]
        ),
    }


def _validate_rendered_html(
    html_text: str,
    *,
    evidence: RegenerationEvidence,
) -> None:
    required = (
        f"<h1>{_h(evidence.display_name)}</h1>",
        evidence.route_identity.bound_track_name,
        evidence.current_status.summary,
        evidence.reference_itinerary.caveat,
        "P0",
        "P1",
        "P2",
    )
    missing = [text for text in required if text not in html_text]
    if missing:
        raise RouteContextRegenerationError(
            "deterministic renderer missed required content: " + ", ".join(missing)
        )
    if evidence.current_status.operability == "closed":
        closed_route_required = (
            "未開放路線的脈絡導覽",
            "第 0 道閘門",
            "不得直接套用為今日規劃模板",
            "等待官方恢復「其他路線」",
        )
        missing_closed_route = [
            text for text in closed_route_required if text not in html_text
        ]
        if missing_closed_route:
            raise RouteContextRegenerationError(
                "closed-route briefing missed required gate copy: "
                + ", ".join(missing_closed_route)
            )
    visible_blocked = [
        term
        for term in BLOCKED_EDITORIAL_TERMS
        if term in html_text and term not in {"artifact"}
    ]
    allowed_nonvisible = ("Scout deterministic route-context renderer",)
    visible_blocked = [
        term
        for term in visible_blocked
        if not any(term in allowed for allowed in allowed_nonvisible)
    ]
    if visible_blocked:
        raise RouteContextRegenerationError(
            "rendered briefing contains blocked internal terms: "
            + ", ".join(sorted(set(visible_blocked)))
        )


def _archive_ref(generated_at: str) -> Path:
    parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    stamp = parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(
        "outputs/briefings/archive/"
        f"route_context_briefing.pre_scout_ai_regeneration_{stamp}.html"
    )


def _safe_project_path(project_root: Path, ref: Path) -> Path:
    if ref.is_absolute():
        raise RouteContextRegenerationError(f"workspace ref must be relative: {ref}")
    root = project_root.resolve()
    resolved = (root / ref).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise RouteContextRegenerationError(f"workspace ref escapes project: {ref}")
    return resolved


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RouteContextRegenerationError(f"invalid JSON artifact {path}: {exc}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _hero_image(workspace: dict[str, Any]) -> dict[str, Any]:
    images = workspace.get("images") or []
    for image in images:
        text = " ".join(
            str(image.get(key) or "") for key in ("alt", "caption", "context_layer")
        )
        if image.get("url") and any(term in text for term in ("地圖", "路線", "古道")):
            return image
    return next((image for image in images if image.get("url")), {})


def _point_label(point: dict[str, Any]) -> str:
    return str(
        point.get("display_label")
        or point.get("label")
        or point.get("name")
        or point.get("title")
        or "未命名節點"
    ).strip()


def _context_label(value: Any) -> str:
    return {
        "resource_context": "中繼／資源脈絡",
        "viewpoint": "展望與觀察脈絡",
        "risk_context": "地形風險脈絡",
        "route_context": "路線脈絡",
    }.get(str(value or ""), "路線證據節點")


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    return [str(value)]


def _format_km(value: Any) -> str:
    try:
        return f"{float(value) / 1000.0:.1f} km"
    except (TypeError, ValueError):
        return "待查"


def _format_m(value: Any) -> str:
    try:
        return f"{float(value):,.0f} m"
    except (TypeError, ValueError):
        return "待查"


def _format_elevation_range(route: dict[str, Any]) -> str:
    return (
        f"{_format_m(route.get('elevation_min_m'))}"
        f"–{_format_m(route.get('elevation_max_m'))}"
    )


def _provider_name(base_url: str | None, call_result: dict[str, object]) -> str:
    metadata = _string_mapping(call_result.get("response_metadata"))
    if metadata.get("provider_name"):
        return metadata["provider_name"].casefold()
    if base_url and "openrouter.ai" in base_url.casefold():
        return "openrouter"
    return "openai-compatible"


def _serialize_usage(result: object) -> dict[str, int]:
    usage_value = getattr(result, "usage", None)
    usage = usage_value() if callable(usage_value) else usage_value
    return {
        field: int(value)
        for field in (
            "requests",
            "tool_calls",
            "input_tokens",
            "cache_write_tokens",
            "cache_read_tokens",
            "output_tokens",
        )
        if isinstance((value := getattr(usage, field, None)), int)
    }


def _serialize_response_metadata(result: object) -> dict[str, str]:
    response_value = getattr(result, "response", None)
    response = response_value() if callable(response_value) else response_value
    return {
        field: str(value)
        for field in (
            "finish_reason",
            "model_name",
            "provider_name",
            "provider_response_id",
        )
        if (value := getattr(response, field, None)) is not None
    }


def _integer_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(item)
        for key, item in value.items()
        if isinstance(item, int)
    }


def _aggregate_usage(call_results: list[dict[str, object]]) -> dict[str, int]:
    aggregate: dict[str, int] = {}
    for result in call_results:
        for key, item in _integer_mapping(result.get("usage")).items():
            aggregate[key] = aggregate.get(key, 0) + item
    return aggregate


def _model_attempt_record(
    *,
    attempt_number: int,
    prompt_sha256: str,
    call_result: dict[str, object],
    status: str,
    validation_error: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "attempt": attempt_number,
        "prompt_sha256": prompt_sha256,
        "status": status,
        "usage": _integer_mapping(call_result.get("usage")),
        "response_metadata": _string_mapping(call_result.get("response_metadata")),
    }
    if validation_error:
        record["validation_error"] = validation_error
    return record


def _editorial_validation_error(exc: Exception) -> str:
    if isinstance(exc, RouteContextRegenerationError):
        return str(exc)
    return f"Scout AI editorial plan is invalid: {exc}"


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)[:1000]
        for key, item in value.items()
        if item is not None
    }


def _boundary() -> dict[str, bool]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "model_wrote_html": False,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_error(message: str, secret: str) -> str:
    return message.replace(secret, "[REDACTED]") if secret else message


def _h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --ink: #17231f;
      --muted: #627069;
      --forest: #214f43;
      --forest-dark: #14372f;
      --moss: #7c8c55;
      --clay: #a95f3e;
      --gold: #c7a45b;
      --paper: #fffdf7;
      --page: #eef1eb;
      --line: #d8ded5;
      --danger: #8f2f26;
      --danger-bg: #fff2ec;
      --shadow: 0 18px 48px rgba(27, 49, 40, .13);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(33, 79, 67, .035) 1px, transparent 1px),
        linear-gradient(rgba(33, 79, 67, .035) 1px, transparent 1px),
        var(--page);
      background-size: 28px 28px;
      font-family: "Noto Sans TC", "PingFang TC", system-ui, sans-serif;
      line-height: 1.65;
    }
    a { color: var(--forest); }
    .hero {
      max-width: 1320px;
      min-height: 620px;
      margin: 28px auto 0;
      padding: 54px;
      border-radius: 34px;
      background: var(--forest-dark);
      color: white;
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(360px, .95fr);
      gap: 42px;
      align-items: stretch;
      overflow: hidden;
      box-shadow: var(--shadow);
    }
    .hero-copy { align-self: center; }
    .document-mode {
      display: inline-block;
      margin: 0 0 16px;
      padding: 7px 12px;
      border-radius: 999px;
      background: #d9c68b;
      color: var(--forest-dark);
      font-size: 13px;
      font-weight: 900;
    }
    .hero-status {
      max-width: 620px;
      margin: 0 0 22px;
      padding: 16px 18px;
      border: 1px solid rgba(255, 220, 202, .65);
      border-radius: 16px;
      background: rgba(143, 47, 38, .32);
    }
    .hero-status strong { display: block; color: #ffe4d8; font-size: 18px; }
    .hero-status p { margin: 6px 0 0; color: #fff2ec; }
    .eyebrow, .section-kicker, .card-kicker {
      margin: 0 0 12px;
      color: #d9c68b;
      font-weight: 800;
      letter-spacing: .09em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      max-width: 10ch;
      font-family: "Noto Serif TC", "Songti TC", serif;
      font-size: clamp(58px, 7vw, 102px);
      line-height: .98;
      letter-spacing: -.05em;
    }
    .subtitle {
      max-width: 28em;
      margin: 28px 0;
      color: #e6eee9;
      font-size: clamp(20px, 2vw, 28px);
    }
    .hero-pills { display: flex; flex-wrap: wrap; gap: 10px; }
    .hero-pills span {
      padding: 8px 13px;
      border: 1px solid rgba(255,255,255,.3);
      border-radius: 999px;
      color: #eff5f1;
      font-size: 14px;
    }
    .hero-media {
      min-height: 500px;
      margin: 0;
      border-radius: 24px;
      overflow: hidden;
      background: #0f2a24;
      display: flex;
      flex-direction: column;
    }
    .hero-media img {
      width: 100%;
      height: 100%;
      min-height: 450px;
      object-fit: cover;
      flex: 1;
    }
    .hero-media figcaption {
      padding: 10px 14px;
      color: #dce8e2;
      font-size: 12px;
    }
    nav {
      position: sticky;
      top: 0;
      z-index: 10;
      margin-top: 24px;
      padding: 12px 20px;
      background: rgba(238, 241, 235, .92);
      backdrop-filter: blur(18px);
      border-block: 1px solid var(--line);
    }
    nav > div {
      max-width: 1240px;
      margin: auto;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      scrollbar-width: thin;
    }
    nav a {
      flex: none;
      padding: 8px 12px;
      border-radius: 999px;
      color: var(--forest-dark);
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
    }
    nav a:hover { background: white; }
    main { max-width: 1240px; margin: 0 auto; padding: 24px 0 80px; }
    section {
      margin: 22px 0;
      padding: 42px;
      scroll-margin-top: 74px;
      border: 1px solid var(--line);
      border-radius: 28px;
      background: var(--paper);
      box-shadow: 0 8px 28px rgba(27, 49, 40, .06);
    }
    .section-heading {
      display: grid;
      grid-template-columns: 56px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
      margin-bottom: 28px;
    }
    .section-heading > span {
      color: var(--clay);
      font-size: 14px;
      font-weight: 900;
    }
    h2 {
      margin: 0;
      max-width: 22ch;
      font-family: "Noto Serif TC", "Songti TC", serif;
      font-size: clamp(34px, 4vw, 58px);
      line-height: 1.08;
      letter-spacing: -.035em;
    }
    h3, h4 { line-height: 1.35; }
    .lead { color: #34453e; font-size: 20px; }
    .decision-grid {
      display: grid;
      grid-template-columns: 2fr repeat(3, 1fr);
      gap: 14px;
    }
    .decision-grid article, .logistics-grid article, .story-card,
    .layer-card, .identity-board, .reader-grid article {
      border: 1px solid var(--line);
      border-radius: 20px;
      background: white;
    }
    .status-card { padding: 24px; }
    .status-card.blocked {
      border-color: #d89a84;
      background: var(--danger-bg);
    }
    .status-card h3 { margin: 6px 0 10px; color: var(--danger); font-size: 26px; }
    .metric-card { padding: 20px; }
    .metric-card span, .atlas-summary span { color: var(--muted); font-size: 13px; }
    .metric-card strong {
      display: block;
      margin: 8px 0;
      color: var(--forest);
      font-size: 28px;
    }
    .metric-card p { margin: 0; color: var(--muted); font-size: 13px; }
    .hard-gate {
      margin-top: 18px;
      padding: 22px 24px;
      border: 2px solid #d89a84;
      border-radius: 18px;
      background: var(--danger-bg);
    }
    .hard-gate span {
      display: block;
      color: var(--danger);
      font-size: 12px;
      font-weight: 900;
      letter-spacing: .08em;
    }
    .hard-gate strong {
      display: block;
      margin-top: 4px;
      color: var(--danger);
      font-size: 22px;
    }
    .hard-gate p { margin-bottom: 0; }
    .source-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
    .source-chips a {
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(33, 79, 67, .09);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }
    .reader-grid, .logistics-grid, .story-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin-top: 18px;
    }
    .reader-grid article, .logistics-grid article, .story-card { padding: 24px; }
    .reader-grid li, .logistics-grid li { margin: 8px 0; }
    .identity-board {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(280px, .7fr);
      gap: 22px;
      padding: 28px;
    }
    .identity-board aside {
      padding: 22px;
      border-radius: 16px;
      background: #edf3ef;
    }
    dl { display: grid; gap: 8px; }
    dl div { display: grid; grid-template-columns: 110px 1fr; gap: 12px; }
    dt { color: var(--muted); }
    dd { margin: 0; font-weight: 750; }
    .story-card > span, .layer-card > span {
      color: var(--clay);
      font-size: 12px;
      font-weight: 900;
    }
    .section-intro {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 20px;
    }
    .caveat {
      max-width: 360px;
      padding: 12px 16px;
      border-left: 4px solid var(--clay);
      background: #fff4e8;
      font-weight: 800;
    }
    .day-list { display: grid; gap: 10px; }
    .day-card {
      display: grid;
      grid-template-columns: 70px 1fr;
      gap: 18px;
      padding: 16px 18px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: white;
    }
    .day-card > span {
      display: grid;
      width: 52px;
      height: 52px;
      place-items: center;
      border-radius: 50%;
      background: var(--forest);
      color: white;
      font-weight: 900;
    }
    .day-card h3 { margin: 0; font-size: 19px; }
    .day-card p { margin: 5px 0 0; color: var(--muted); }
    .application-card { background: #f0f5f1 !important; }
    .application-card h3 { color: var(--forest); font-size: 30px; }
    .flow {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-top: 18px;
    }
    .flow span {
      padding: 15px;
      border-radius: 14px;
      background: var(--forest-dark);
      color: white;
      font-size: 14px;
    }
    .flow b { color: #dbc982; margin-right: 8px; }
    .atlas-summary {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }
    .atlas-summary article {
      padding: 20px;
      border-radius: 16px;
      background: var(--forest-dark);
      color: white;
    }
    .atlas-summary b { display: block; margin-top: 5px; font-size: 28px; }
    .point-rail {
      display: flex;
      gap: 12px;
      overflow-x: auto;
      padding-bottom: 8px;
    }
    .point-card {
      flex: 0 0 220px;
      min-height: 150px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: white;
    }
    .point-card > span { color: var(--clay); font-weight: 900; }
    .point-card h3 { margin: 12px 0 5px; }
    .point-card p { color: var(--muted); }
    .visual-grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .visual-grid figure {
      grid-column: span 4;
      margin: 0;
      overflow: hidden;
      border-radius: 18px;
      background: #e5e9e4;
    }
    .visual-grid figure:first-child { grid-column: span 8; grid-row: span 2; }
    .visual-grid img { width: 100%; height: 260px; object-fit: cover; display: block; }
    .visual-grid figure:first-child img { height: 100%; min-height: 532px; }
    .visual-grid figcaption { padding: 10px 12px; font-size: 13px; }
    .visual-grid figcaption span {
      margin-right: 8px;
      color: var(--clay);
      font-weight: 900;
    }
    .empty-state {
      padding: 38px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      color: var(--muted);
      text-align: center;
    }
    .layer-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 14px;
    }
    .layer-card { min-height: 220px; padding: 22px; }
    .layer-card h4 { margin: 10px 0 6px; font-size: 19px; }
    .layer-card small {
      display: block;
      margin-top: 18px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
      color: var(--muted);
    }
    .p2-board {
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: 24px;
      align-items: center;
      padding: 28px;
      border-radius: 18px;
      background: #ebe5d4;
    }
    .p2-board > div { display: flex; flex-direction: column; }
    .p2-board strong { color: var(--forest); font-size: 72px; line-height: 1; }
    .memory-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
    .memory-chips span {
      padding: 7px 11px;
      border-radius: 999px;
      background: white;
      border: 1px solid var(--line);
      font-size: 13px;
    }
    .source-summary { display: flex; gap: 12px; margin-bottom: 16px; }
    .source-summary span {
      padding: 10px 14px;
      border-radius: 12px;
      background: #edf2ee;
    }
    .source-summary b { margin-right: 6px; color: var(--forest); }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; background: white; }
    th, td { padding: 13px; border-bottom: 1px solid var(--line); text-align: left; }
    th { color: var(--muted); font-size: 12px; }
    .tier {
      display: inline-block;
      min-width: 38px;
      padding: 3px 7px;
      border-radius: 999px;
      text-align: center;
      font-weight: 900;
    }
    .tier-p0 { background: #dcecdf; color: #1d5b3b; }
    .tier-p1 { background: #e6e8f2; color: #3a476f; }
    .tier-p2 { background: #efe5d5; color: #77532e; }
    .source-boundary {
      margin-top: 16px;
      padding: 18px;
      border-left: 4px solid var(--gold);
      background: #fbf6e9;
    }
    footer {
      padding: 48px 24px 70px;
      background: var(--forest-dark);
      color: white;
      text-align: center;
    }
    footer strong { font-family: "Noto Serif TC", serif; font-size: 28px; }
    footer p { color: #c7d6cf; }
    @media (max-width: 900px) {
      .hero { margin: 0; padding: 30px 22px; border-radius: 0; grid-template-columns: 1fr; }
      .hero-media { min-height: 300px; }
      .hero-media img { min-height: 280px; }
      main { padding-inline: 12px; }
      section { padding: 28px 20px; }
      .decision-grid, .reader-grid, .logistics-grid, .story-grid,
      .identity-board, .layer-grid, .atlas-summary, .flow {
        grid-template-columns: 1fr;
      }
      .section-intro { align-items: start; flex-direction: column; }
      .visual-grid { display: block; }
      .visual-grid figure { margin: 12px 0; }
      .visual-grid figure:first-child img, .visual-grid img { min-height: 0; height: auto; }
      .p2-board { grid-template-columns: 1fr; }
      h1 { font-size: 56px; }
    }
    @media print {
      nav { display: none; }
      body { background: white; }
      .hero, section { box-shadow: none; break-inside: avoid; }
      .hero { margin: 0; border-radius: 0; }
    }
    """


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Use Scout AI cloud editorial planning and deterministic evidence "
            "compilation to rebuild one Route Context briefing."
        )
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL_CONFIG)
    parser.add_argument("--skill", type=Path, default=DEFAULT_SKILL_PATH)
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--env-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = regenerate_route_context_briefing(
            project_root=args.project_root,
            evidence_path=args.evidence,
            model_config_path=args.model_config,
            skill_path=args.skill,
            model_name=args.model,
            timeout_seconds=args.timeout_seconds,
            env_file=args.env_file,
        )
    except RouteContextRegenerationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
