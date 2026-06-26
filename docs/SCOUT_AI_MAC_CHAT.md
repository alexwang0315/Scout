# Scout AI Mac Chat

`scout-ai-os-mac-chat` runs a Mac-local browser interface while using the Scout
hardware as the Scout AI OS server by default.

```text
Mac browser
  -> http://127.0.0.1:8765
  -> Mac-local proxy
  -> http://scout.local:9120
  -> Scout AI OS /requests
```

The UI follows the existing admin/debug/pretrip Assistant layout pattern:
server status, surface selection, suggested prompts, conversation, route detail,
permission detail, action-plan detail, and raw JSON.

## Start The Scout Hardware Server

On the Scout hardware:

```bash
cd /home/alexwang0315/scout-ai-os-hardware-current
venv/bin/python -m uvicorn scout.main:app --host 0.0.0.0 --port 9120
```

The Mac UI expects the Scout hardware API to expose:

- `GET /capabilities`
- `POST /requests`

## Start The Mac Chat UI

On the Mac:

```bash
cd /Users/alexwang0315/scout-fusion-live-gates
./venv/bin/scout-ai-os-mac-chat --target-url http://scout.local:9120
```

Open:

```text
http://127.0.0.1:8765
```

The target can also be set with:

```bash
SCOUT_AI_SERVER_URL=http://scout.local:9120 ./venv/bin/scout-ai-os-mac-chat
```

## Mac Local Fallback Mode

When the Scout hardware is offline or under repair, the same UI can fall back to
the Mac-local Scout assistant provider:

```bash
cd /Users/alexwang0315/scout-fusion
./venv/bin/scout-ai-os-mac-chat \
  --target-url http://scout.local:9120 \
  --local-fallback \
  --fallback-model openrouter:z-ai/glm-5.2 \
  --fallback-project-id chilai_nanhua_day1 \
  --fallback-workspace-root /path/to/pretrip/workspace
```

The CLI loads `.env` by default before constructing the fallback provider. It
does not print token values. For OpenRouter-backed models, `.env` or the shell
must provide `OPENROUTER_API_KEY`.

Fallback behavior:

- The Mac proxy first tries the Scout hardware `/requests` endpoint.
- If the hardware request fails, the Mac process calls Scout's read-only
  Pydantic AI v2 assistant provider.
- The fallback provider reuses the existing assistant safety wrapper, skill
  routing, and Scout workspace tools.
- The JSON response includes `response_source=mac_local_pydantic_ai_v2` and
  preserves the remote error as `remote_error`.
- Missing local workspace/project context is reported as an evidence gap; it is
  not treated as proof of safety.

## Local API

The Mac proxy exposes:

```text
GET  /api/config
GET  /api/server
POST /api/chat
```

`POST /api/chat` sends this shape to the Scout hardware `/requests` endpoint:

```json
{
  "user_id": "mac-chat-user",
  "user_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
  "active_context": {
    "surface": "pretrip",
    "client": "scout_mac_chat"
  }
}
```

## Boundary

The Mac UI is a client/proxy only.

- It does not call `/safety/*`.
- It does not mutate Phase 1 L0-L4 runtime safety truth.
- It does not send outbound Telegram/SMS/satellite messages.
- It does not control hardware.
- Local fallback is opt-in with `--local-fallback`; fallback model output is
  still read-only model interpretation and is never runtime safety truth.

Session-local UI operation requests may return `scout_ui_action_plan.v0`.
Workflow requests may install or require approval according to the Scout AI OS
permission gate on the hardware server.
