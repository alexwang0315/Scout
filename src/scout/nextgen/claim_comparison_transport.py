"""Fail-closed HTTP egress for the fixed subject-selection comparison only."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

_INSTRUCTIONS = (
    "Return only the requested typed candidate analysis. "
    "Never claim mission, route, permission, emergency, "
    "notification, hardware, or runtime safety authority. "
    "Preserve unknown and conflict."
)


def _hash(value) -> str:
    encoded = value.encode() if isinstance(value, str) else json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _valid_repair_message(message: dict) -> bool:
    if set(message) != {"role", "content"} or message.get("role") != "user" or not isinstance(message.get("content"), str):
        return False
    match = re.fullmatch(
        r"Previous output failed schema validation\. Repair attempt [0-9]+\. "
        r"Return only the requested JSON object; preserve the original evidence\. (\[.*\])",
        message["content"],
    )
    if match is None:
        return False
    errors = json.loads(match.group(1))
    return all(isinstance(item, dict) and set(item) == {"path", "error"}
               and isinstance(item["path"], list)
               and all(part == "claim_ids" or type(part) is int for part in item["path"])
               and item["error"] in {"missing", "literal_error", "value_error", "tuple_type", "json_invalid",
                                      "string_type", "string_too_short", "extra_forbidden"} for item in errors)


class ClaimComparisonTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, review: dict, config, audit_dir: Path, inner=None) -> None:
        if (config.locality.value != "cloud" or config.specialist_output_mode != "compact_advisory"
                or config.structured_output_mode != "native" or config.native_retry_context_mode != "fresh_attempt"):
            raise ValueError("comparison transport requires a pinned native compact cloud runtime")
        self._config = config
        self._cases = {(item["model_prompt_sha256"], item["wire_output_schema_sha256"]): item for item in review["cases"]}
        self._audit_dir = audit_dir
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        record = {"schema_version": "scout.claim_comparison_egress.v0", "egress_id": str(uuid4()),
                  "runtime_id": self._config.runtime_id, "requested_model": self._config.model_id,
                  "started_at": datetime.now(UTC).isoformat(),
                  "candidate_only": True, "runtime_safety_truth": False}
        try:
            body = json.loads(await request.aread())
            if request.method != "POST" or str(request.url) != self._config.normalized_base_url.rstrip("/") + "/chat/completions":
                raise ValueError("unapproved comparison endpoint")
            if (not isinstance(body, dict) or body.get("model") != self._config.model_id
                    or set(body) - {"model", "messages", "response_format", "stream", "temperature"}
                    or body.get("stream", False) is not False):
                raise ValueError("unapproved comparison request shape")
            messages = body["messages"]
            if (len(messages) not in (2, 3) or messages[0] != {"role": "system", "content": _INSTRUCTIONS}
                    or set(messages[1]) != {"role", "content"} or messages[1]["role"] != "user"
                    or not isinstance(messages[1]["content"], str)
                    or (len(messages) == 3 and not _valid_repair_message(messages[2]))):
                raise ValueError("unapproved comparison messages")
            output = body["response_format"]
            if (output["type"] != "json_schema" or set(output) != {"type", "json_schema"}
                    or set(output["json_schema"]) != {"name", "schema", "strict"}
                    or output["json_schema"]["name"] != "SelectedClaimSubjects"
                    or output["json_schema"]["strict"] is not True):
                raise ValueError("unapproved comparison output mode")
            hashes = (_hash(messages[1]["content"]), _hash(output["json_schema"]["schema"]))
            case = self._cases.get(hashes)
            if case is None:
                raise ValueError("unapproved comparison prompt or schema")
            record.update(case_id=case["case_id"], model_prompt_sha256=hashes[0], wire_output_schema_sha256=hashes[1],
                          messages_sha256=_hash(messages), body_sha256=_hash(body), allowed=True)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            reason = str(exc) if str(exc).startswith("unapproved comparison ") else type(exc).__name__
            self._write({**record, "allowed": False, "status": "rejected_before_network", "reason": reason})
            raise ValueError("comparison egress rejected before network") from None
        self._write({**record, "status": "authorized_before_network"})
        try:
            response = await self._inner.handle_async_request(request)
            payload = json.loads(await response.aread())
            self._write({**record, "status": "response_received", "http_status": response.status_code,
                         "completed_at": datetime.now(UTC).isoformat(),
                         "observed_model": payload.get("model"), "usage": payload.get("usage"),
                         "response_body_sha256": _hash(payload)})
            return response
        except Exception as exc:
            self._write({**record, "status": "transport_failed", "error_type": type(exc).__name__})
            raise

    def _write(self, record: dict) -> None:
        path = self._audit_dir / f"{record['egress_id']}.{record['status']}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")

    async def aclose(self) -> None:
        await self._inner.aclose()
