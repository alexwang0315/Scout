from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from scout_energy_models import aggregate_sha256
from scout_wearable_admin import (
    WEARABLE_DAILY_ENERGY_OVERVIEW_FILENAME,
    WEARABLE_DAILY_HOME_PREVIEW_FILENAME,
    WEARABLE_DAILY_HOME_PREVIEW_HTML_FILENAME,
    build_daily_energy_overview,
)


def build_daily_home_preview(
    *,
    inventory_root: Path,
    reference_date: date | None = None,
    write_artifact: bool = True,
) -> dict[str, Any]:
    outputs_dir = inventory_root / "outputs"
    overview_path = outputs_dir / WEARABLE_DAILY_ENERGY_OVERVIEW_FILENAME
    if reference_date is not None or not overview_path.exists():
        overview = build_daily_energy_overview(
            inventory_root=inventory_root,
            reference_date=reference_date,
            write_artifact=True,
        )["overview"]
    else:
        overview = json.loads(overview_path.read_text(encoding="utf-8"))

    preview = build_daily_home_preview_model(
        overview,
        overview_path=overview_path,
    )
    preview_path = outputs_dir / WEARABLE_DAILY_HOME_PREVIEW_FILENAME
    html_path = outputs_dir / WEARABLE_DAILY_HOME_PREVIEW_HTML_FILENAME
    if write_artifact:
        _write_json(preview_path, preview)
        html_path.write_text(
            render_daily_home_preview_html(preview),
            encoding="utf-8",
        )

    return {
        "artifact_kind": "scout_wearable_daily_home_preview_result",
        "persisted": write_artifact,
        "preview_path": str(preview_path),
        "html_path": str(html_path),
        "source_provider": preview["source_provider"],
        "source_path": preview["source_path"],
        "sha256": preview["sha256"],
        "preview": preview,
        "data_quality": preview["data_quality"],
        "privacy": preview["privacy"],
        "boundary": preview["boundary"],
        "mutation": {
            "daily_home_preview_written": write_artifact,
            "daily_energy_overview_written": True,
            "source_file_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "remote_upload_performed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def build_daily_home_preview_model(
    overview: dict[str, Any],
    *,
    overview_path: Path,
) -> dict[str, Any]:
    _assert_overview_boundary(overview)
    trend = overview["trend_vs_baseline"]
    trend_cards = [
        _trend_card("7 day", trend["acute_7_day_load"]),
        _trend_card("28 day", trend["recent_28_day_baseline"]),
        _trend_card("90 day", trend["stable_90_day_baseline"]),
    ]
    max_load = max((card["load_sum"] for card in trend_cards), default=1.0) or 1.0
    for card in trend_cards:
        card["bar_percent"] = round(min(100.0, card["load_sum"] / max_load * 100.0), 1)

    preview_sha = aggregate_sha256(
        [
            overview["sha256"],
            {
                "artifact": "daily_home_preview",
                "reference_date": overview["reference_date"],
                "reserve_band": overview["current_reserve_band"],
                "trend_cards": trend_cards,
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_daily_home_preview",
        "artifact_version": "wearable_daily_home_preview.v1",
        "source_provider": overview["source_provider"],
        "source_path": overview["source_path"],
        "sha256": preview_sha,
        "surface": "daily_home_preview",
        "reference_date": overview["reference_date"],
        "source_artifacts": [
            {
                "artifact_kind": overview["artifact_kind"],
                "source_path": str(overview_path),
                "sha256": overview["sha256"],
            }
        ],
        "hero": {
            "title": "Scout Daily",
            "reserve_band": overview["current_reserve_band"],
            "reserve_label": _label(overview["current_reserve_band"]),
            "reserve_score": overview["reserve_score"],
            "advisory_label": "baseline-relative trend",
        },
        "trend_cards": trend_cards,
        "trend_markers": {
            "acute_load_ratio": trend["acute_load_ratio"],
            "acute_load_z": trend["acute_load_z"],
            "recovery_debt_z": trend["recovery_debt_z"],
        },
        "recent_load_and_recovery_explanation": overview[
            "recent_load_and_recovery_explanation"
        ],
        "next_day_soft_cue": overview["next_day_soft_cue"],
        "display_language_policy": overview["display_language_policy"],
        "data_quality": overview["data_quality"],
        "privacy": overview["privacy"],
        "boundary": overview["boundary"],
    }


def render_daily_home_preview_html(preview: dict[str, Any]) -> str:
    hero = preview["hero"]
    trend_cards = preview["trend_cards"]
    next_day = preview["next_day_soft_cue"]
    explanations = preview["recent_load_and_recovery_explanation"]
    metadata_json = json.dumps(
        preview,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).replace("</", "<\\/")
    cards_html = "\n".join(_render_trend_card(card) for card in trend_cards)
    explanations_html = "\n".join(
        f"<li>{escape(str(line))}</li>" for line in explanations[:4]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scout Daily</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f6f2;
      --ink: #17201b;
      --muted: #637067;
      --panel: #ffffff;
      --line: #d9dfd7;
      --green: #2f6f4e;
      --blue: #2f5f8f;
      --amber: #ac6b2f;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    main {{
      display: flex;
      justify-content: center;
      padding: 24px 14px;
    }}
    .phone {{
      width: min(100%, 390px);
      min-height: 760px;
      border: 1px solid var(--line);
      border-radius: 28px;
      background: #fbfcfa;
      box-shadow: 0 18px 52px rgba(28, 38, 31, 0.16);
      overflow: hidden;
    }}
    .top {{
      padding: 26px 22px 18px;
      background: #e9f0eb;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.05;
      font-weight: 750;
    }}
    .date {{
      margin-top: 7px;
      color: var(--muted);
      font-size: 13px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1fr 118px;
      gap: 14px;
      align-items: center;
      padding: 18px 0 0;
    }}
    .band {{
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      border-radius: 999px;
      padding: 0 12px;
      background: #fff7ed;
      color: #6e3d0e;
      font-size: 13px;
      font-weight: 700;
      text-transform: lowercase;
    }}
    .subline {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.35;
    }}
    .score {{
      width: 112px;
      aspect-ratio: 1;
      display: grid;
      place-items: center;
      border-radius: 50%;
      background: conic-gradient(var(--green) calc(var(--score) * 1%), #e1e6df 0);
    }}
    .score-inner {{
      width: 82px;
      aspect-ratio: 1;
      display: grid;
      place-items: center;
      border-radius: 50%;
      background: #fbfcfa;
      font-size: 30px;
      font-weight: 760;
    }}
    section {{
      padding: 18px 18px 0;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 14px;
      font-weight: 760;
      color: #26362d;
    }}
    .trend-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }}
    .trend-card {{
      min-height: 118px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 10px;
    }}
    .trend-window {{
      font-size: 13px;
      font-weight: 760;
    }}
    .trend-load {{
      margin-top: 8px;
      font-size: 22px;
      font-weight: 760;
      color: var(--blue);
    }}
    .trend-meta {{
      margin-top: 2px;
      font-size: 11px;
      color: var(--muted);
    }}
    .bar {{
      margin-top: 10px;
      height: 8px;
      border-radius: 999px;
      background: #edf0eb;
      overflow: hidden;
    }}
    .bar span {{
      display: block;
      height: 100%;
      width: var(--bar);
      background: var(--amber);
    }}
    .cue {{
      border: 1px solid #d6dfd8;
      border-radius: 8px;
      background: #f7fbf8;
      padding: 13px;
    }}
    .cue-title {{
      margin: 0;
      font-size: 17px;
      font-weight: 760;
    }}
    .cue-text {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.42;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    .quality {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      padding-bottom: 20px;
    }}
    .quality div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 9px 10px;
      min-height: 54px;
    }}
    .quality span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
    }}
    .quality strong {{
      display: block;
      margin-top: 3px;
      font-size: 14px;
    }}
    @media (max-width: 430px) {{
      main {{
        padding: 0;
      }}
      .phone {{
        width: 100%;
        min-height: 100vh;
        border: 0;
        border-radius: 0;
        box-shadow: none;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <article class="phone" aria-label="Scout Daily preview">
      <header class="top">
        <h1>{escape(str(hero['title']))}</h1>
        <div class="date">{escape(str(preview['reference_date']))}</div>
        <div class="hero">
          <div>
            <span class="band">{escape(str(hero['reserve_label']))}</span>
            <div class="subline">{escape(str(hero['advisory_label']))}</div>
          </div>
          <div class="score" style="--score: {int(hero['reserve_score'])}">
            <div class="score-inner">{int(hero['reserve_score'])}</div>
          </div>
        </div>
      </header>
      <section>
        <h2>Baseline trend</h2>
        <div class="trend-grid">
          {cards_html}
        </div>
      </section>
      <section>
        <h2>Next</h2>
        <div class="cue">
          <p class="cue-title">{escape(str(next_day['label']))}</p>
          <p class="cue-text">{escape(str(next_day['text']))}</p>
        </div>
      </section>
      <section>
        <h2>Recent load</h2>
        <ul>{explanations_html}</ul>
      </section>
      <section class="quality">
        <div><span>Heart rate</span><strong>{escape(str(preview['data_quality']['heart_rate_confidence']))}</strong></div>
        <div><span>Provider values</span><strong>{escape(str(preview['data_quality']['provider_value_confidence']))}</strong></div>
      </section>
    </article>
  </main>
  <script type="application/json" id="scoutDailyHomePreviewArtifact">
{metadata_json}
  </script>
</body>
</html>
"""


def _render_trend_card(card: dict[str, Any]) -> str:
    return f"""<div class="trend-card">
  <div class="trend-window">{escape(str(card['label']))}</div>
  <div class="trend-load">{escape(str(card['load_sum']))}</div>
  <div class="trend-meta">{int(card['activity_count'])} activities</div>
  <div class="trend-meta">{escape(str(card['daily_average_load']))} per day</div>
  <div class="bar" aria-hidden="true"><span style="--bar: {card['bar_percent']}%"></span></div>
</div>"""


def _trend_card(label: str, window: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "window_days": window["window_days"],
        "activity_count": window["activity_count"],
        "load_sum": window["load_sum"],
        "mean_activity_load": window["mean_activity_load"],
        "daily_average_load": window["daily_average_load"],
    }


def _label(value: str) -> str:
    return value.replace("_", " ")


def _assert_overview_boundary(overview: dict[str, Any]) -> None:
    boundary = overview.get("boundary", {})
    privacy = overview.get("privacy", {})
    if boundary.get("medical_diagnosis") is not False:
        raise ValueError("daily home preview requires medical_diagnosis=false")
    if boundary.get("phase1_runtime_safety_truth") is not False:
        raise ValueError("daily home preview cannot be Phase 1 runtime safety truth")
    if boundary.get("safety_api_calls_allowed") is not False:
        raise ValueError("daily home preview cannot call safety APIs")
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared"):
        raise ValueError("daily home preview cannot share raw health payloads or tracks")
    if privacy.get("exact_timestamps_shared") or privacy.get("home_work_trace_shared"):
        raise ValueError("daily home preview cannot share exact timestamps or home/work traces")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
