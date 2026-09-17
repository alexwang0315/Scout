#!/usr/bin/env python3
"""Run only the explicitly reviewed comparison through the existing MCP server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from scout.nextgen.claim_comparison_transport import ClaimComparisonTransport
from scout.nextgen.intelligence_mcp_http_server import main as server_main
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig, build_praison_openai_compatible_runtime
from scout.nextgen.praison_service import EvidenceCatalog, PraisonIntelligenceService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--comparison-input-review", type=Path, required=True)
    parser.add_argument("--egress-audit-dir", type=Path, required=True)
    args, server_args = parser.parse_known_args()
    review = json.loads(args.comparison_input_review.read_bytes())

    def service_factory(*, mode, evidence_catalog_path, model_runtime_config_path):
        if mode != "praison-openai-compatible":
            raise ValueError("comparison service requires the configured real model backend")
        config = OpenAICompatibleBackendConfig.from_json_file(model_runtime_config_path)
        transport = ClaimComparisonTransport(review=review, config=config, audit_dir=args.egress_audit_dir)
        runtime = build_praison_openai_compatible_runtime(
            config=config, http_client=httpx.AsyncClient(transport=transport, trust_env=False),
        )
        return PraisonIntelligenceService(
            runtime=runtime, evidence_catalog=EvidenceCatalog.from_json_file(evidence_catalog_path), max_concurrency=1,
        )

    return server_main(argv=server_args, service_factory=service_factory)


if __name__ == "__main__":
    raise SystemExit(main())
