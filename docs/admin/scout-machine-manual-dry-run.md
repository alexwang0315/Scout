# Scout Machine Manual Dry Run Package

這份文件定義 Scout machine manual dry-run package。它是 operator worksheet 與
evidence template，不是自動部署工具。

## Boundary

- 不連 Pi。
- 不啟動 Docker。
- 不啟動 Ollama 或本地模型。
- 不呼叫 live `/safety/*` mutation。
- 不送 outbound、SOS、SMS 或 satellite。
- 不控制 hardware provider。
- 不改 Phase 1 safety decision。
- 不寫 ObservedFact、Brain、IncidentStore 或 review decision。

## Local Validation

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_scout_machine_dry_run_package.py
```

## Operator Worksheet

Operator 必須在真機 dry-run 前填入：

- target id
- host label
- runtime base URL
- `/data/scout` data root
- `pi-field` runtime profile
- service start method
- stop conditions checked

`tests/fixtures/hardware/scout_machine_dry_run_package.example.json` 是 evidence
template 範例；不得寫入 token、secret、api key 或 authorization value。
