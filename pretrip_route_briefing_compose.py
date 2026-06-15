from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any, Sequence


ARTIFACT_KIND = "pretrip_route_briefing_compose"
SCHEMA_VERSION = "route_briefing_compose.v1"
DEFAULT_OUTPUT_REF = "outputs/briefings/route_briefing.html"


def compose_pretrip_route_briefing(
    request_path: Path | str,
    *,
    output_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    request_file = Path(request_path)
    request = _load_json_object(request_file)
    project_root = _optional_path(request.get("project_root"))
    generated_at = str(request.get("generated_at") or _utc_now())
    route_id = _slug(str(request.get("route_id") or request.get("project_id") or "route"))
    title = str(request.get("title") or request.get("route_name") or "Route Briefing")
    output_ref = str(request.get("output_ref") or f"outputs/briefings/{route_id}_briefing.html")
    resolved_output = Path(output_path) if output_path is not None else None
    if resolved_output is None and project_root is not None:
        resolved_output = project_root / output_ref

    source_refs = _list_of_dicts(request.get("source_refs"))
    route_summary = _dict(request.get("route_summary"))
    context_layers = _dict(request.get("context_layers"))
    observation_stops = _list_of_dicts(request.get("observation_stops"))
    itinerary_options = _list_of_dicts(request.get("itinerary_options"))
    route_points = _list_of_dicts(request.get("route_points"))

    boundary = _boundary(workspace_file_mutation_allowed=bool(resolved_output and not dry_run))
    html = _build_html(
        title=title,
        route_id=route_id,
        generated_at=generated_at,
        route_summary=route_summary,
        context_layers=context_layers,
        observation_stops=observation_stops,
        itinerary_options=itinerary_options,
        route_points=route_points,
        source_refs=source_refs,
        boundary=boundary,
    )

    if resolved_output is not None and not dry_run:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(html, encoding="utf-8")

    return {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "route_id": route_id,
        "title": title,
        "generated_at": generated_at,
        "source_count": len(source_refs),
        "context_layer_count": len(context_layers),
        "observation_stop_count": len(observation_stops),
        "itinerary_option_count": len(itinerary_options),
        "output_ref": output_ref if resolved_output is not None else None,
        "output_path": str(resolved_output) if resolved_output is not None else None,
        "writes_performed": bool(resolved_output and not dry_run),
        "html_preview": html if resolved_output is None or dry_run else None,
        "boundary": boundary,
        "integration_notes": {
            "input_policy": "operator_reviewed_sources_only",
            "network_research_policy": "live_fetch_must_happen_outside_runtime_or_through_an_explicitly_approved_connector",
            "answer_visibility": [
                "route briefing outputs should be indexed into route_context evidence",
                "Scout AI answer synthesis should cite briefing source_refs and preserve candidate-only wording",
            ],
        },
    }


def _build_html(
    *,
    title: str,
    route_id: str,
    generated_at: str,
    route_summary: dict[str, Any],
    context_layers: dict[str, Any],
    observation_stops: list[dict[str, Any]],
    itinerary_options: list[dict[str, Any]],
    route_points: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    boundary: dict[str, Any],
) -> str:
    recommended_days = route_summary.get("recommended_days") or route_summary.get("duration") or "需要人工確認"
    hero_note = route_summary.get("summary") or route_summary.get("description") or "Candidate route briefing generated from reviewed pretrip evidence."
    season_note = route_summary.get("season_note") or "出發前需重新查核官方公告、天氣與道路。"
    current_status = route_summary.get("current_status") or "未提供現況摘要"
    risk_note = route_summary.get("risk_note") or "本簡報不是 runtime safety truth，僅供行前討論與人工審核。"
    layer_cards = "\n".join(
        _card(str(layer_name), _join_items(layer_value))
        for layer_name, layer_value in context_layers.items()
    ) or _card("context", "No context layers were supplied.")
    route_point_cards = "\n".join(
        _card(
            str(point.get("name") or point.get("id") or "route point"),
            _join_items(
                [
                    point.get("why_it_matters"),
                    point.get("observation_prompt"),
                    point.get("safety_note"),
                ]
            ),
        )
        for point in route_points
    ) or _card("route points", "No route points were supplied.")
    stop_cards = "\n".join(
        _card(
            f"{stop.get('minutes', 3)} min - {stop.get('name', 'observation stop')}",
            _join_items([stop.get("observe"), stop.get("do_not_stop_if")]),
        )
        for stop in observation_stops
    ) or _card("observation stops", "No observation stops were supplied.")
    itinerary_rows = "\n".join(
        "<tr>"
        f"<td>{_h(option.get('label', 'option'))}</td>"
        f"<td>{_h(option.get('schedule', ''))}</td>"
        f"<td>{_h(option.get('best_for', ''))}</td>"
        f"<td>{_h(option.get('tradeoff', ''))}</td>"
        "</tr>"
        for option in itinerary_options
    ) or "<tr><td colspan=\"4\">No itinerary options were supplied.</td></tr>"
    source_items = "\n".join(
        "<li>"
        f"<strong>{_h(source.get('title', source.get('url', 'source')))}</strong>"
        f"<span>{_h(source.get('url', ''))}</span>"
        f"<em>{_h(source.get('usage', ''))}</em>"
        "</li>"
        for source in source_refs
    ) or "<li><strong>No source refs supplied</strong><span></span><em></em></li>"

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(title)}</title>
  <style>
    :root {{
      --bg: #edf2ef;
      --paper: #fffefa;
      --ink: #17201b;
      --muted: #58615b;
      --line: #cfd8d2;
      --forest: #143a31;
      --gold: #b07920;
      --rust: #9b4434;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: linear-gradient(90deg, rgba(31, 91, 71, .07) 1px, transparent 1px),
                  linear-gradient(0deg, rgba(31, 91, 71, .05) 1px, transparent 1px),
                  var(--bg);
      background-size: 28px 28px;
      font-family: "Noto Sans TC", "PingFang TC", system-ui, sans-serif;
      line-height: 1.62;
    }}
    header {{
      padding: 56px 24px 44px;
      color: #fffefa;
      background: var(--forest);
    }}
    main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 30px 0 56px; }}
    h1, h2 {{ margin: 0; font-family: "Noto Serif TC", "Songti TC", serif; letter-spacing: 0; }}
    h1 {{ max-width: 900px; font-size: clamp(42px, 7vw, 82px); line-height: 1.02; }}
    h2 {{ font-size: clamp(28px, 4vw, 48px); line-height: 1.1; }}
    p {{ margin: 0; }}
    .lead {{ max-width: 840px; margin-top: 18px; color: #e8f1ec; font-size: 19px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }}
    .pill {{ border: 1px solid rgba(255,255,255,.32); border-radius: 999px; padding: 7px 12px; font-weight: 800; }}
    section {{
      margin: 0 0 24px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(22px, 4vw, 40px);
      background: rgba(255,254,250,.96);
    }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 22px; }}
    .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; background: #fffefa; }}
    .card strong {{ display: block; color: var(--forest); font-size: 18px; }}
    .card span {{ display: block; margin-top: 8px; color: var(--muted); }}
    .alert {{ border-left: 5px solid var(--rust); margin-top: 18px; padding: 12px 14px; background: #fff0e9; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 22px; background: #fffefa; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 12px; text-align: left; vertical-align: top; }}
    th {{ color: #fffefa; background: var(--forest); }}
    ul.sources {{ display: grid; gap: 10px; padding: 0; list-style: none; }}
    .sources li {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fffefa; }}
    .sources span, .sources em {{ display: block; color: var(--muted); word-break: break-word; }}
    @media (max-width: 760px) {{
      .grid {{ grid-template-columns: 1fr; }}
      table, thead, tbody, tr, td {{ display: block; width: 100%; }}
      thead {{ display: none; }}
      tr {{ border: 1px solid var(--line); border-radius: 8px; margin-bottom: 12px; padding: 12px; }}
      td {{ border-bottom: 1px solid var(--line); padding: 9px 0; }}
      td:last-child {{ border-bottom: 0; }}
    }}
  </style>
</head>
<body>
  <header>
    <p>Scout pretrip route briefing - {_h(route_id)}</p>
    <h1>{_h(title)}</h1>
    <p class="lead">{_h(hero_note)}</p>
    <div class="meta">
      <span class="pill">建議天數：{_h(recommended_days)}</span>
      <span class="pill">產生時間：{_h(generated_at)}</span>
      <span class="pill">candidate-only</span>
    </div>
  </header>
  <main>
    <section>
      <h2>行程結論</h2>
      <div class="grid">
        {_card("建議天數", recommended_days)}
        {_card("現況摘要", current_status)}
        {_card("季節提醒", season_note)}
      </div>
      <p class="alert">{_h(risk_note)}</p>
    </section>
    <section>
      <h2>沿線脈絡層</h2>
      <div class="grid">{layer_cards}</div>
    </section>
    <section>
      <h2>路線節點</h2>
      <div class="grid">{route_point_cards}</div>
    </section>
    <section>
      <h2>值得停 3 分鐘的觀察點</h2>
      <div class="grid">{stop_cards}</div>
    </section>
    <section>
      <h2>行程版本</h2>
      <table>
        <thead><tr><th>版本</th><th>安排</th><th>適合</th><th>取捨</th></tr></thead>
        <tbody>{itinerary_rows}</tbody>
      </table>
    </section>
    <section>
      <h2>資料來源</h2>
      <ul class="sources">{source_items}</ul>
      <p class="alert">Boundary: runtime_safety_truth={str(boundary["runtime_safety_truth"]).lower()},
      network_calls_made={str(boundary["network_calls_made"]).lower()},
      model_output_is_runtime_truth={str(boundary["model_output_is_runtime_truth"]).lower()}.</p>
    </section>
  </main>
</body>
</html>
"""


def _card(title: str, body: Any) -> str:
    return f"<article class=\"card\"><strong>{_h(title)}</strong><span>{_h(body)}</span></article>"


def _join_items(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "；".join(f"{key}: {_join_items(item)}" for key, item in value.items() if item)
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item)
    return str(value)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("route briefing request must be a JSON object")
    return payload


def _optional_path(value: Any) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    return Path(str(value))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _boundary(*, workspace_file_mutation_allowed: bool) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "model_output_is_runtime_truth": False,
        "network_calls_made": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "workspace_file_mutation_allowed": workspace_file_mutation_allowed,
        "requires_operator_source_review": True,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    chars = []
    for char in value.strip().lower():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", " "}:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "route"


def _h(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compose a Scout pretrip route briefing HTML artifact.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = compose_pretrip_route_briefing(
            args.input,
            output_path=args.output,
            dry_run=bool(args.dry_run),
        )
    except Exception as exc:  # noqa: BLE001 - CLI returns structured tool errors.
        payload = {
            "artifact_kind": ARTIFACT_KIND,
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "error": repr(exc),
            "boundary": _boundary(workspace_file_mutation_allowed=False),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
