# Scout Pi Docker Build Dry Run

這份 dry-run gate 只檢查 Docker runtime-core contract，不執行 Docker。

## Boundary

- 不執行 `docker build`。
- 不啟動 container。
- 不啟動 Ollama 或本地模型。
- 不啟動 k3s、MQTT、NATS、Coral、Jetson。
- 不開 network call。

## Validation

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_scout_pi_docker_build_dry_run.py
```

預期結果：`Dockerfile.pi` 與 `docker-compose.pi.yml` 固定 `linux/arm64`、`/data/scout`、
`pi-field`、live hardware off、AI/local model off、event bus none，並且
`requirements.pi.txt` 不拉入模型或 event bus 套件。
