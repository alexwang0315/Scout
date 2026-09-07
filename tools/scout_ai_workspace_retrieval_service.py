"""Isolated Workspace retrieval specialist on the existing MCP queue transport."""

from __future__ import annotations

import argparse
from pathlib import Path

from scout.nextgen.intelligence_mcp_http_server import main as server_main
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig
from scout.nextgen.praison_service import PraisonIntelligenceService
from scout.nextgen.workspace_retrieval import WorkspaceRetrievalScope
from scout.nextgen.workspace_retrieval_runtime import WorkspaceRetrievalRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--retrieval-scope", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    args, server_args = parser.parse_known_args()

    def service_factory(*, mode, evidence_catalog_path, model_runtime_config_path):
        if mode != "praison-openai-compatible" or evidence_catalog_path is not None:
            raise ValueError("Workspace retrieval requires an independent model and no preloaded evidence")
        runtime = WorkspaceRetrievalRuntime(
            root=args.workspace_root, scope=WorkspaceRetrievalScope.model_validate_json(args.retrieval_scope.read_bytes()),
            config=OpenAICompatibleBackendConfig.from_json_file(model_runtime_config_path), audit_dir=args.audit_dir,
        )
        return PraisonIntelligenceService(runtime=runtime, max_concurrency=1)

    return server_main(argv=server_args, service_factory=service_factory)


if __name__ == "__main__":
    raise SystemExit(main())
