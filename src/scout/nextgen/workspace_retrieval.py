"""Read-only, request-bound Workspace tools for experimental native retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter, model_validator

from scout.nextgen.intelligence_gateway import IntelligenceRequest, WorkspaceBinding, stable_payload_hash
from scout.nextgen.praison_service import CapabilitySession, EvidenceCatalogItem
from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.workspace_query import (
    ArgMaxQuery, CountQuery, ExistsQuery, FilterQuery, GroupByQuery, InspectQuery,
    SafeField, WorkspaceArtifactSelector, WorkspacePredicateOperator,
)
from scout.services.workspace_query import WorkspaceQueryService

RetrievalQuery = Annotated[
    InspectQuery | CountQuery | ExistsQuery | FilterQuery | GroupByQuery | ArgMaxQuery,
    Field(discriminator="operation"),
]
QUERY_ADAPTER = TypeAdapter(RetrievalQuery)
CAPABILITIES = frozenset({"workspace.catalog.search", "workspace.schema.read", "workspace.query.read"})


class WorkspaceToolPredicate(SchemaModel):
    field: SafeField
    operator: WorkspacePredicateOperator
    value: int | float | str | bool | None | list[int | float | str | bool | None]


class WorkspaceQueryToolInput(SchemaModel):
    """Flat native tool schema; operation-specific validation remains deterministic."""

    operation: Literal["inspect", "count", "exists", "filter", "group_by", "argmax"]
    artifact: WorkspaceArtifactSelector
    predicates: list[WorkspaceToolPredicate] = Field(description="All filter conditions, combined with AND. Use [] only for an unfiltered query.")
    fields: list[SafeField] = Field(description="Fields to return; use [] for count/exists, explicit fields for inspect/filter/argmax.")
    limit: int = Field(default=20, ge=1, le=100)
    field: SafeField | None = None
    sort_by: SafeField | None = None
    descending: bool = False
    subtract_field: SafeField | None = None

    def as_query(self) -> RetrievalQuery:
        return QUERY_ADAPTER.validate_python(self.model_dump(mode="json", exclude_defaults=True))

    @model_validator(mode="after")
    def validate_operation(self):
        self.as_query()
        return self


def normalize_native_query(arguments: dict) -> RetrievalQuery:
    # Earlier traces used the internal discriminated union directly.
    if "predicates" not in arguments or "fields" not in arguments:
        return QUERY_ADAPTER.validate_python(arguments)
    return WorkspaceQueryToolInput.model_validate(arguments).as_query()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_path(root: Path, source_ref: str) -> Path:
    ref = Path(source_ref)
    if ref.is_absolute() or any(part.startswith(".") for part in ref.parts) or ref.suffix not in {".json", ".geojson"}:
        raise ValueError("Workspace source is outside the read scope")
    path = (root / ref).resolve(strict=True)
    path.relative_to(root.resolve(strict=True))
    return path


def require_external_audit_dir(root: Path, audit_dir: Path) -> None:
    if audit_dir.resolve().is_relative_to(root.resolve()):
        raise ValueError("experimental audit output must be outside the Workspace")


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class ArtifactReadGrant(SchemaModel):
    source_ref: NonEmptyStr
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fields: tuple[NonEmptyStr, ...]
    collection_path: str | None = None
    project_ref_key: str | None = None


class WorkspaceRetrievalScope(SchemaModel):
    schema_version: Literal["scout.workspace_retrieval_scope.v0"] = "scout.workspace_retrieval_scope.v0"
    workspace_id: NonEmptyStr
    artifacts: tuple[ArtifactReadGrant, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    def binding(self) -> WorkspaceBinding:
        digest = stable_payload_hash(self.model_dump(mode="json"))
        return WorkspaceBinding(workspace_id=self.workspace_id, workspace_revision=digest,
                                mission_id=f"{self.workspace_id}:retrieval-experiment", mission_version="read-only-v0",
                                input_hash=digest)

    def verify(self, root: Path) -> None:
        refs = [item.source_ref for item in self.artifacts]
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate Workspace source grants")
        root = root.resolve(strict=True)
        for item in self.artifacts:
            path = source_path(root, item.source_ref)
            if file_hash(path) != item.sha256:
                raise ValueError("Workspace source binding changed")


class WorkspaceAnswerFact(SchemaModel):
    name: NonEmptyStr
    value: int | float | str | bool | None
    evidence_id: NonEmptyStr
    data_path: NonEmptyStr


class WorkspaceRetrievalAnswer(SchemaModel):
    answer: NonEmptyStr
    status: Literal["answered", "partial", "unknown"]
    facts: tuple[WorkspaceAnswerFact, ...] = ()
    evidence_ids: tuple[NonEmptyStr, ...]
    uncertainties: tuple[str, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def _value_at(value, path: str):
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _field_type(payload, path):
    try:
        value = _value_at(payload, path)
    except (KeyError, IndexError, ValueError, TypeError):
        return "absent"
    return "null" if value is None else type(value).__name__


class WorkspaceRetrievalTools:
    def __init__(self, *, root: Path, scope: WorkspaceRetrievalScope, request: IntelligenceRequest,
                 capabilities: CapabilitySession, cancellation: threading.Event, audit_dir: Path) -> None:
        scope.verify(root)
        require_external_audit_dir(root, audit_dir)
        expected = scope.binding()
        if (request.workspace_binding.model_dump(exclude={"generated_at"}) != expected.model_dump(exclude={"generated_at"})
                or request.mission_id != expected.mission_id):
            raise ValueError("Workspace retrieval request binding mismatch")
        self.root, self.scope, self.request = root.resolve(), scope, request
        self.capabilities, self.cancellation, self.audit_dir = capabilities, cancellation, audit_dir
        self._lock = threading.RLock()
        self._receipts: list[dict] = []
        self._discovered: set[str] = set()
        self._inspected: set[str] = set()
        self._native_call_id: str | None = None

    def native_call(self, tool_call_id, function, **arguments):
        with self._lock:
            self._native_call_id = tool_call_id
            try:
                return function(**arguments)
            finally:
                self._native_call_id = None

    @property
    def receipts(self) -> tuple[dict, ...]:
        return tuple(self._receipts)

    def _begin(self, capability):
        if self.cancellation.is_set() or self.request.capability_grant.is_expired():
            raise ValueError("Workspace retrieval cancelled or capability expired")
        self.capabilities.use(capability)
        self.scope.verify(self.root)

    def _record(self, tool: str, arguments: dict, result: dict) -> dict:
        evidence_id = f"workspace-tool:{uuid4()}"
        body = {**result, "evidence_id": evidence_id, "candidate_only": True, "runtime_safety_truth": False}
        receipt = {"tool": tool, "arguments": arguments, "result": body,
                   "native_tool_call_id": self._native_call_id,
                   "request_id": str(self.request.request_id), "input_hash": self.request.workspace_binding.input_hash,
                   "recorded_at": datetime.now(UTC).isoformat(), "output_hash": stable_payload_hash(body)}
        write_new(self.audit_dir / f"tool-{len(self._receipts):02d}.json", receipt)
        self._receipts.append(receipt)
        return body

    def search_workspace_artifacts(self, query: str = "") -> dict:
        """Search authorized Workspace filenames/ref keys. Empty query lists the full scoped inventory; no file contents are returned."""
        with self._lock:
            self._begin("workspace.catalog.search")
            terms = re.findall(r"[\w]+", query.casefold())
            matches = [item for item in self.scope.artifacts
                       if not terms or any(term in f"{item.source_ref} {item.project_ref_key or ''}".casefold() for term in terms)]
            self._discovered.update(item.source_ref for item in matches)
            return self._record("search_workspace_artifacts", {"query": query}, {
                "status": "available" if matches else "no_match_in_scope", "scope_complete": True,
                "results": [{"source_ref": item.source_ref, "project_ref_key": item.project_ref_key,
                             "source_hash": item.sha256} for item in matches],
                "limitations": ["search covers the authorized artifact inventory only"],
            })

    def inspect_workspace_artifact(self, source_ref: str) -> dict:
        """Read an artifact's permitted field types and collection path after discovering its filename."""
        with self._lock:
            self._begin("workspace.schema.read")
            item = self._grant(source_ref, require_inspected=False)
            payload = json.loads((self.root / item.source_ref).read_bytes())
            collection = _value_at(payload, item.collection_path) if item.collection_path else payload
            sample = next(iter(collection), {}) if isinstance(collection, list) else collection
            fields = [{"field": field, "record_type": _field_type(sample, field),
                       "root_type": _field_type(payload, field)} for field in item.fields]
            self.scope.verify(self.root)
            self._inspected.add(source_ref)
            return self._record("inspect_workspace_artifact", {"source_ref": source_ref}, {
                "status": "available", "source_ref": source_ref, "source_hash": item.sha256,
                "collection_path": item.collection_path, "fields": fields, "collection_selection": "explicit",
                "query_semantics": "null collection_path targets the root itself; exists evaluates predicates; inspect reads fields without predicates",
            })

    def _grant(self, source_ref, *, require_inspected=True):
        item = next((entry for entry in self.scope.artifacts if entry.source_ref == source_ref), None)
        if item is None or source_ref not in self._discovered:
            raise ValueError("discover an authorized Workspace artifact before reading it")
        if require_inspected and source_ref not in self._inspected:
            raise ValueError("inspect the Workspace artifact schema before querying")
        return item

    def query_workspace(self, request: RetrievalQuery) -> dict:
        """Execute a typed read-only query on a discovered and inspected artifact. Use count for exact totals; inspect with fields for root metadata. Cite returned evidence_id and result data paths."""
        with self._lock:
            self._begin("workspace.query.read")
            request = QUERY_ADAPTER.validate_python(request if isinstance(request, dict) else request.model_dump(mode="python"))
            item = self._grant(request.artifact.source_ref)
            if request.artifact.project_ref_key is not None or request.artifact.collection_path != item.collection_path:
                raise ValueError("use the discovered source_ref and inspected collection_path")
            fields = [*request.fields, *(predicate.field for predicate in request.predicates)]
            fields += [value for name in ("field", "sort_by", "subtract_field") if (value := getattr(request, name, None))]
            if set(fields) - set(item.fields) or (isinstance(request, (FilterQuery, ArgMaxQuery, InspectQuery)) and not request.fields):
                raise ValueError("query only explicit permitted fields from schema inspection")
            if isinstance(request, InspectQuery) and request.predicates:
                return self._record("query_workspace", request.model_dump(mode="json"), {
                    "status": "error", "summary": "inspect does not evaluate predicates; use exists, count or filter",
                    "results": [], "source_refs": [item.source_ref], "root_cause": "inspect_predicates_unsupported",
                    "safe_retry": True, "next_actions": ["use exists to obtain a source-bound boolean condition"],
                })
            result = WorkspaceQueryService(self.root, discover_nested_collections=False).execute(request).model_dump(mode="json")
            result = {**result, "collection_selection": "explicit", "selected_collection_path": item.collection_path}
            # Aggregate queries include implicit record identities outside the granted fields.
            aggregate_fields = ({"count"} if isinstance(request, CountQuery) else
                                {"exists", "matching_count"} if isinstance(request, ExistsQuery) else None)
            result["results"] = [{"data": {key: value for key, value in row["data"].items()
                                           if aggregate_fields is None or key in aggregate_fields},
                                  "source_hash": row["source_hash"]} for row in result["results"]]
            self.scope.verify(self.root)
            return self._record("query_workspace", request.model_dump(mode="json"), result)

    def validate_answer(self, answer: WorkspaceRetrievalAnswer) -> WorkspaceRetrievalAnswer:
        self.scope.verify(self.root)
        if self.request.capability_grant.is_expired() or self.cancellation.is_set():
            raise ValueError("Workspace answer outlived its authorization")
        by_id = {item["result"]["evidence_id"]: item for item in self._receipts}
        if not answer.evidence_ids or set(answer.evidence_ids) - set(by_id):
            raise ValueError("answer must cite evidence retrieved during this request")
        if answer.status == "answered" and not answer.facts:
            raise ValueError("answered output requires source-bound scalar facts")
        for fact in answer.facts:
            if fact.evidence_id not in answer.evidence_ids or by_id[fact.evidence_id]["tool"] != "query_workspace":
                raise ValueError("answer fact requires a query receipt citation")
            if not fact.data_path.startswith("results."):
                raise ValueError("answer facts must address queried data")
            try:
                actual = _value_at(by_id[fact.evidence_id]["result"], fact.data_path)
            except (KeyError, TypeError, IndexError, ValueError):
                raise ValueError("answer fact data path was not retrieved") from None
            if isinstance(actual, (dict, list)) or type(actual) is not type(fact.value) or actual != fact.value:
                raise ValueError("answer fact differs from the retrieved scalar")
        return answer

    def evidence(self) -> tuple[EvidenceCatalogItem, ...]:
        return tuple(EvidenceCatalogItem(
            evidence_id=item["result"]["evidence_id"], source_ref=f"workspace-query:{self.request.request_id}:{index}",
            source_type="workspace_readonly_tool_receipt", content_hash=item["output_hash"],
            summary=json.dumps(item["result"], ensure_ascii=False), method=item["tool"],
            generated_at=datetime.fromisoformat(item["recorded_at"]),
        ) for index, item in enumerate(self._receipts))
