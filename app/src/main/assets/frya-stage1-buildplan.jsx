import { useState } from "react";

const C = {
  bg: "#07090c",
  surface: "#0d1117",
  card: "#111820",
  border: "#1c2333",
  accent: "#22d3ee",
  accentDim: "#0c3d4a",
  green: "#4ade80",
  greenDim: "#14532d",
  warn: "#fb923c",
  warnDim: "#431407",
  red: "#f87171",
  redDim: "#450a0a",
  purple: "#c084fc",
  purpleDim: "#3b0764",
  yellow: "#fbbf24",
  muted: "#475569",
  text: "#e2e8f0",
  textDim: "#94a3b8",
  faint: "#334155",
};

const TAB = [
  { id: "sprint", label: "🗓 Sprint Plan" },
  { id: "server", label: "🖥 Server Aufräumen" },
  { id: "agent", label: "🤖 Agent (exakter Code)" },
  { id: "app", label: "📱 Android App" },
  { id: "paperless", label: "📄 Paperless Setup" },
];

const Box = ({ children, color = C.border, bg = C.card, style = {} }) => (
  <div style={{ border: `1px solid ${color}`, borderRadius: 10, padding: "14px 16px", background: bg, ...style }}>{children}</div>
);

const Chip = ({ children, color = C.accentDim, text = C.accent, style = {} }) => (
  <span style={{ background: color, color: text, fontSize: 10, fontFamily: "monospace", padding: "2px 8px", borderRadius: 4, marginRight: 4, letterSpacing: 1, fontWeight: 700, textTransform: "uppercase", whiteSpace: "nowrap", ...style }}>{children}</span>
);

const SectionTitle = ({ children, color = C.accent }) => (
  <div style={{ fontFamily: "monospace", fontSize: 11, letterSpacing: 3, textTransform: "uppercase", color, marginBottom: 14, borderBottom: `1px solid ${color}33`, paddingBottom: 8 }}>{children}</div>
);

const Code = ({ children }) => (
  <pre style={{ background: "#030507", border: `1px solid ${C.faint}`, borderRadius: 8, padding: "12px 14px", fontSize: 11, color: "#a5f3fc", fontFamily: "'Fira Code', monospace", overflow: "auto", margin: "8px 0", whiteSpace: "pre-wrap", lineHeight: 1.7 }}>
    {children}
  </pre>
);

// ─── SPRINT TAB ───────────────────────────────────────────────────────────────
function SprintTab() {
  const phases = [
    {
      id: "P0", label: "Phase 0 — Server bereinigen", duration: "Tag 1 / ~2h", color: C.red,
      tasks: [
        { t: "n8n stoppen + aus compose.yml entfernen", cmd: "docker compose stop n8n\n# compose.yml: n8n-Service + n8n_data Volume entfernen\ndocker compose down\ndocker volume rm dms-staging_n8n_data" },
        { t: "RAM-Check nach Bereinigung", cmd: "free -h  # Erwartet: ~600-800 MB frei zusätzlich" },
        { t: "paperless-gpt hinzufügen (compose.yml Ergänzung)", cmd: null },
      ],
    },
    {
      id: "P1", label: "Phase 1 — Paperless konfigurieren", duration: "Tag 1-2 / ~4h", color: C.green,
      tasks: [
        { t: "Audit-Log aktivieren", cmd: "PAPERLESS_AUDIT_LOG_ENABLED=true" },
        { t: "Custom Fields anlegen: buchungsstatus, rechnungsbetrag_netto, faelligkeit, iban_lieferant", cmd: "# Paperless Web UI → Settings → Custom Fields" },
        { t: "Correspondents + Document Types definieren (branchenspezifisch)", cmd: "# via Paperless REST API oder Web UI\n# Types: Eingangsrechnung, Ausgangsrechnung, Vertrag, Kontoauszug, Sonstiges" },
        { t: "Workflow: Post-Consume → paperless-gpt-auto tag setzen", cmd: "# Trigger: Document Added\n# Action: Add Tag 'paperless-gpt-auto'" },
        { t: "Webhook Workflow: nach gpt-Verarbeitung → Agent notifizieren", cmd: "# Trigger: Document Updated (tag=gpt-processed)\n# Action: Webhook POST https://agent.staging.myfrya.de/webhook/document" },
        { t: "FRYA-Tags anlegen: zu-buchen, gebucht, freigegeben, abgelehnt", cmd: "# Agent setzt diese Tags nach Approval-Flow" },
      ],
    },
    {
      id: "P2", label: "Phase 2 — FRYA Agent bauen", duration: "Tag 2-5 / ~3 Tage", color: C.purple,
      tasks: [
        { t: "Projektstruktur anlegen + Dockerfile", cmd: null },
        { t: "LiteLLM config.py + openai/anthropic/ollama Support", cmd: null },
        { t: "LangGraph: Orchestrator Graph mit 4 Nodes", cmd: null },
        { t: "Paperless Tool-Set (REST API Wrapper)", cmd: null },
        { t: "Telegram Bot (Webhooks, Inline Keyboards, File-Send)", cmd: null },
        { t: "GoBD Audit-Log (PostgreSQL append-only table)", cmd: null },
        { t: "Memory System (agent.md, daily-log, PG memory table)", cmd: null },
        { t: "Webhook-Endpoint /webhook/document", cmd: null },
        { t: "Health-Check /health", cmd: null },
        { t: "Startup-Nachricht Telegram testen", cmd: null },
      ],
    },
    {
      id: "P3", label: "Phase 3 — Android App", duration: "Tag 4-8 / ~4 Tage", color: C.accent,
      tasks: [
        { t: "Flutter Project Setup + Dependencies", cmd: "# flutter, dart, http, websocket, camera, file_picker, pdf_viewer" },
        { t: "Auth Screen: Agent-URL + Paperless-URL + API Token", cmd: null },
        { t: "Chat Screen: WebSocket/SSE zum Agent", cmd: null },
        { t: "Scanner Screen: ML Kit Document Scanner", cmd: null },
        { t: "Upload Flow: Scan → POST Paperless API /api/documents/post_document/", cmd: null },
        { t: "Document Viewer: GET Paperless API → PDF in-app anzeigen", cmd: null },
        { t: "Push Notification bei Agent-Nachricht", cmd: "# FCM oder Telegram Deep Link als Fallback" },
        { t: "APK Build + auf Server deployen (via Traefik)", cmd: null },
      ],
    },
    {
      id: "P4", label: "Phase 4 — Integration testen", duration: "Tag 8-10", color: C.yellow,
      tasks: [
        { t: "End-to-End Test: Foto scannen → gebucht (Stage 2: manuell)", cmd: null },
        { t: "Webhook Flow testen (manuelle doc_id)", cmd: null },
        { t: "Telegram Approval Gate durchspielen", cmd: null },
        { t: "GoBD Audit-Log prüfen", cmd: null },
        { t: "App + Agent + Paperless parallel live", cmd: null },
      ],
    },
  ];

  const [active, setActive] = useState("P0");
  const phase = phases.find(p => p.id === active);

  return (
    <div>
      <SectionTitle>Stage 1 Sprint Plan — Paperless + Agent + App</SectionTitle>
      <Box color={C.green} bg="#0a1a0a" style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, color: C.green, fontWeight: 700, marginBottom: 4 }}>🎯 Stage 1 Scope (klar definiert)</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          {["✅ Paperless DMS (Scan, OCR, Archiv, paperless-gpt)", "✅ FRYA Agent (LangGraph, LiteLLM, Telegram, GoBD-Log)", "✅ Android App (Scan, Agent-Chat, Dokument-Viewer)", "❌ Akaunting (Stage 2)", "❌ n8n (entfernen)"].map(i => (
            <div key={i} style={{ fontSize: 12, color: i.startsWith("✅") ? C.green : C.red, background: C.card, border: `1px solid ${i.startsWith("✅") ? C.greenDim : C.redDim}`, borderRadius: 6, padding: "4px 10px" }}>{i}</div>
          ))}
        </div>
      </Box>
      <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
        {phases.map(p => (
          <button key={p.id} onClick={() => setActive(p.id)} style={{
            background: active === p.id ? p.color + "22" : C.surface,
            color: active === p.id ? p.color : C.textDim,
            border: `1px solid ${active === p.id ? p.color : C.border}`,
            borderRadius: 8, padding: "8px 14px", fontSize: 11, cursor: "pointer", fontFamily: "monospace",
          }}>
            <div style={{ fontWeight: 700 }}>{p.id}</div>
            <div style={{ fontSize: 10 }}>{p.duration}</div>
          </button>
        ))}
      </div>
      <Box color={phase.color} bg={phase.color + "11"} style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 700, color: phase.color, fontSize: 14 }}>{phase.label}</div>
        <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>{phase.duration}</div>
      </Box>
      {phase.tasks.map((task, i) => (
        <Box key={i} style={{ marginBottom: 8, padding: "8px 14px" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <div style={{ minWidth: 20, height: 20, borderRadius: "50%", background: phase.color + "22", border: `1px solid ${phase.color}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: phase.color, flexShrink: 0 }}>{i + 1}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: C.text, marginBottom: task.cmd ? 4 : 0 }}>{task.t}</div>
              {task.cmd && <Code>{task.cmd}</Code>}
            </div>
          </div>
        </Box>
      ))}
    </div>
  );
}

// ─── SERVER TAB ───────────────────────────────────────────────────────────────
function ServerTab() {
  return (
    <div>
      <SectionTitle>Server bereinigen + paperless-gpt hinzufügen</SectionTitle>
      <Box color={C.red} bg={C.redDim + "55"} style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.red, marginBottom: 6 }}>n8n entfernen — RAM freigeben</div>
        <Code>{`# 1. n8n stoppen
cd /opt/dms-staging
docker compose stop n8n

# 2. In compose.yml den n8n-Service entfernen (kompletter Block)
# services:
#   n8n:        ← LÖSCHEN
#     image: ...
#     ...

# 3. Neu starten
docker compose down
docker compose up -d

# 4. Volume bereinigen (ERST NACH BACKUP!)
docker volume rm dms-staging_n8n_data

# 5. RAM-Check
free -h`}
        </Code>
      </Box>

      <Box color={C.purple} bg={C.purpleDim + "44"} style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.purple, marginBottom: 6 }}>paperless-gpt hinzufügen (compose.yml Ergänzung)</div>
        <Code>{`  paperless-gpt:
    image: ghcr.io/icereed/paperless-gpt:latest
    container_name: frya-paperless-gpt
    restart: unless-stopped
    environment:
      PAPERLESS_BASE_URL: "http://frya-paperless:8000"
      PAPERLESS_API_TOKEN: \${PAPERLESS_TOKEN}
      LLM_PROVIDER: "openai"           # oder "ollama" wenn lokal
      LLM_MODEL: "gpt-4o"             # wird durch LiteLLM ersetzt wenn gewünscht
      VISION_LLM_PROVIDER: "openai"
      VISION_LLM_MODEL: "gpt-4o"
      OPENAI_API_KEY: \${FRYA_OPENAI_API_KEY}
      LLM_LANGUAGE: "German"
      AUTO_TAG: "paperless-gpt-auto"  # Trigger-Tag
      LOG_LEVEL: "info"
    volumes:
      - ./paperless-gpt-prompts:/app/prompts  # Custom Prompts persistent
    networks:
      - frya-internal
    labels:
      - "traefik.enable=false"
      - "com.centurylinklabs.watchtower.enable=true"`}
        </Code>
      </Box>

      <Box color={C.green} bg="#0a1a0a" style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.green, marginBottom: 6 }}>Agent Traefik Route (neu)</div>
        <Code>{`  agent:
    build:
      context: ./agent
    container_name: frya-agent
    restart: unless-stopped
    environment:
      FRYA_LLM_PROVIDER: \${FRYA_LLM_PROVIDER:-openai/gpt-4o}
      FRYA_OPENAI_API_KEY: \${FRYA_OPENAI_API_KEY:?}
      FRYA_PAPERLESS_TOKEN: \${FRYA_PAPERLESS_TOKEN:?}
      FRYA_TELEGRAM_BOT_TOKEN: \${FRYA_TELEGRAM_BOT_TOKEN:?}
      FRYA_TELEGRAM_CHAT_ID: \${FRYA_TELEGRAM_CHAT_ID:?}
      FRYA_DATABASE_URL: "postgresql://frya:pass@frya-db:5432/frya_agent"
    volumes:
      - agent_data:/app/data
    networks:
      - frya-internal
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.agent.rule=Host(\`agent.staging.myfrya.de\`)"
      - "traefik.http.routers.agent.entrypoints=websecure"
      - "traefik.http.routers.agent.tls.certresolver=letsencrypt"
      - "traefik.http.services.agent.loadbalancer.server.port=8001"

volumes:
  agent_data:`}
        </Code>
      </Box>

      <Box color={C.accent} bg={C.accentDim + "44"}>
        <div style={{ fontWeight: 700, color: C.accent, marginBottom: 6 }}>Container-Übersicht nach Bereinigung</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {[
            ["traefik", C.green, "bleibt"],
            ["frya-db (PG16)", C.green, "bleibt"],
            ["frya-mariadb", C.green, "bleibt"],
            ["frya-redis", C.green, "bleibt"],
            ["frya-paperless", C.green, "bleibt"],
            ["frya-tika", C.green, "bleibt"],
            ["frya-gotenberg", C.green, "bleibt"],
            ["frya-akaunting", C.yellow, "bleibt (Stage 2)"],
            ["frya-fastapi-stub", C.muted, "bleibt (unberührt)"],
            ["uptime-kuma", C.green, "bleibt"],
            ["watchtower", C.green, "bleibt"],
            ["frya-paperless-gpt", C.purple, "NEU"],
            ["frya-agent", C.purple, "NEU"],
            ["frya-keys-ui", C.accent, "NEU (aus SC#03)"],
            ["n8n", C.red, "ENTFERNEN"],
          ].map(([name, color, status]) => (
            <div key={name} style={{ background: C.card, border: `1px solid ${color}44`, borderRadius: 6, padding: "4px 10px", fontSize: 11 }}>
              <span style={{ color }}>{name}</span>
              <span style={{ color: C.muted, marginLeft: 6, fontSize: 10 }}>{status}</span>
            </div>
          ))}
        </div>
      </Box>
    </div>
  );
}

// ─── AGENT TAB ────────────────────────────────────────────────────────────────
function AgentTab() {
  const [section, setSection] = useState("structure");
  const sections = [
    { id: "structure", label: "Struktur" },
    { id: "config", label: "config.py" },
    { id: "graph", label: "LangGraph" },
    { id: "tools", label: "Paperless Tools" },
    { id: "telegram", label: "Telegram" },
    { id: "gobd", label: "GoBD Log" },
    { id: "webhook", label: "Webhook" },
  ];

  const content = {
    structure: `agent/
├── Dockerfile
├── requirements.txt
├── main.py                    # FastAPI app + Webhook endpoint
├── config.py                  # Pydantic Settings (LiteLLM-aware)
├── graph/
│   ├── __init__.py
│   ├── agent.py               # LangGraph StateGraph Definition
│   ├── nodes.py               # Orchestrator, Monitor Node-Funktionen
│   └── state.py               # AgentState TypedDict
├── tools/
│   ├── __init__.py
│   ├── paperless.py           # Paperless REST API Tools
│   ├── telegram.py            # Send message, send document, inline keyboard
│   └── gobd_log.py            # GoBD Audit-Log (PostgreSQL append-only)
├── memory/
│   ├── __init__.py
│   ├── manager.py             # Context assembly + daily log
│   └── curator.py             # Nightly: LLM komprimiert Log → memory.md
├── data/                      # Persistent Volume
│   ├── agent.md               # Persona
│   ├── user.md                # Kunden-Profil (leer bis Onboarding)
│   ├── soul.md                # FRYA DNA / Werte
│   ├── memory.md              # Langzeit-Gedächtnis
│   ├── dms-state.md           # Aktueller Systemzustand
│   └── logs/                  # Daily Logs YYYY-MM-DD.md
└── tests/`,

    config: `# config.py
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # LiteLLM — provider-agnostisch
    # Format: "openai/gpt-4o" | "anthropic/claude-sonnet-4-6" | "ollama/qwen2.5:72b"
    llm_provider: str = "openai/gpt-4o"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Paperless
    paperless_url: str = "http://frya-paperless:8000"
    paperless_token: str

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # PostgreSQL (GoBD-Log + Memory)
    database_url: str

    # Paths
    data_dir: Path = Path("/app/data")

    class Config:
        env_prefix = "FRYA_"

settings = Settings()

# LiteLLM completion — Ein Interface, alle Provider
from litellm import acompletion

async def llm_complete(messages: list, max_tokens: int = 1024) -> str:
    response = await acompletion(
        model=settings.llm_provider,
        messages=messages,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content`,

    graph: `# graph/state.py
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: Optional[str]
    doc_id: Optional[int]
    approval_pending: bool
    audit_logged: bool

# graph/agent.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from graph.state import AgentState
from graph.nodes import (
    classify_intent,
    handle_document_webhook,
    handle_query,
    handle_onboarding,
    monitor_check,
    route_intent,
)

def build_graph(checkpointer):
    g = StateGraph(AgentState)

    g.add_node("classify",    classify_intent)
    g.add_node("doc_handler", handle_document_webhook)
    g.add_node("query",       handle_query)
    g.add_node("onboarding",  handle_onboarding)
    g.add_node("monitor",     monitor_check)

    g.set_entry_point("classify")

    g.add_conditional_edges("classify", route_intent, {
        "document":   "doc_handler",
        "query":      "query",
        "onboarding": "onboarding",
        "monitor":    "monitor",
    })

    for node in ["doc_handler", "query", "onboarding", "monitor"]:
        g.add_edge(node, END)

    return g.compile(checkpointer=checkpointer)

# LangGraph Checkpointer = States sind persistent über Telegram-Sessions hinweg
# thread_id = telegram_chat_id`,

    tools: `# tools/paperless.py
import httpx
from config import settings

BASE = settings.paperless_url
HEADERS = {"Authorization": f"Token {settings.paperless_token}"}

async def get_document(doc_id: int) -> dict:
    """Dokument-Metadaten + extrahierter Text von Paperless holen."""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/api/documents/{doc_id}/", headers=HEADERS)
        r.raise_for_status()
        return r.json()

async def get_document_download_url(doc_id: int) -> str:
    """Direkter Download-Link für PDF."""
    return f"{BASE}/api/documents/{doc_id}/download/"

async def set_tag(doc_id: int, tag_id: int):
    """Tag auf Dokument setzen (z.B. 'zu-buchen')."""
    doc = await get_document(doc_id)
    current_tags = doc.get("tags", [])
    if tag_id not in current_tags:
        current_tags.append(tag_id)
        async with httpx.AsyncClient() as c:
            await c.patch(
                f"{BASE}/api/documents/{doc_id}/",
                headers=HEADERS,
                json={"tags": current_tags}
            )

async def set_custom_field(doc_id: int, field_id: int, value: str):
    """Custom Field setzen (z.B. buchungsstatus='zu-buchen')."""
    async with httpx.AsyncClient() as c:
        await c.patch(
            f"{BASE}/api/documents/{doc_id}/",
            headers=HEADERS,
            json={"custom_fields": [{"field": field_id, "value": value}]}
        )

async def search_documents(query: str) -> list:
    """Volltextsuche in Paperless."""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/api/documents/?query={query}", headers=HEADERS)
        return r.json().get("results", [])`,

    telegram: `# tools/telegram.py
import httpx
from config import settings

BOT_URL = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
CHAT_ID = settings.telegram_chat_id

async def send_message(text: str, reply_markup=None):
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as c:
        await c.post(f"{BOT_URL}/sendMessage", json=payload)

async def send_document(doc_id: int, caption: str = ""):
    """Dokument aus Paperless an Telegram senden."""
    from tools.paperless import get_document_download_url, HEADERS
    download_url = get_document_download_url(doc_id)
    async with httpx.AsyncClient() as c:
        # Datei von Paperless holen
        r = await c.get(download_url, headers=HEADERS)
        # An Telegram schicken
        await c.post(
            f"{BOT_URL}/sendDocument",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"document": ("document.pdf", r.content, "application/pdf")}
        )

def approval_keyboard(doc_id: int) -> dict:
    """Inline Keyboard für Buchungs-Approval."""
    return {
        "inline_keyboard": [[
            {"text": "✅ Buchen",     "callback_data": f"approve:{doc_id}"},
            {"text": "✏️ Korrigieren","callback_data": f"edit:{doc_id}"},
            {"text": "❌ Ablehnen",   "callback_data": f"reject:{doc_id}"},
        ]]
    }

async def answer_callback(callback_query_id: str):
    async with httpx.AsyncClient() as c:
        await c.post(f"{BOT_URL}/answerCallbackQuery",
                     json={"callback_query_id": callback_query_id})`,

    gobd: `# tools/gobd_log.py
# GoBD-konformer Audit-Log — APPEND ONLY, niemals UPDATE/DELETE
import asyncpg
import hashlib, json
from datetime import datetime, UTC
from config import settings

async def get_pool():
    return await asyncpg.create_pool(settings.database_url)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS gobd_audit (
    id           BIGSERIAL PRIMARY KEY,
    log_id       UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    timestamp    TIMESTAMPTZ DEFAULT now() NOT NULL,
    agent_id     TEXT NOT NULL,
    action       TEXT NOT NULL,           -- z.B. 'document_received', 'booking_proposed'
    doc_id       INTEGER,                 -- Paperless doc_id wenn relevant
    doc_hash     TEXT,                    -- SHA256 des Originaldokuments
    entity_ref   TEXT,                    -- Akaunting booking_id etc.
    input_json   JSONB,                   -- Was der Agent als Input hatte
    output_json  JSONB,                   -- Was der Agent entschieden hat
    llm_model    TEXT,                    -- z.B. 'gpt-4o'
    approved_by  TEXT,                    -- 'user:maze' | 'agent:auto' | 'system'
    confidence   FLOAT,
    notes        TEXT
);
-- KRITISCH: Keine DELETE/UPDATE-Rechte für den App-User!
-- REVOKE DELETE, UPDATE ON gobd_audit FROM frya_agent_user;
-- Row Level Security oder DB-User ohne diese Rechte
""";

async def log(
    action: str,
    agent_id: str = "orchestrator",
    doc_id: int = None,
    doc_hash: str = None,
    input_data: dict = None,
    output_data: dict = None,
    llm_model: str = None,
    approved_by: str = "agent:auto",
    confidence: float = None,
    notes: str = None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gobd_audit
              (agent_id, action, doc_id, doc_hash, entity_ref,
               input_json, output_json, llm_model, approved_by, confidence, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """,
        agent_id, action, doc_id, doc_hash, None,
        json.dumps(input_data) if input_data else None,
        json.dumps(output_data) if output_data else None,
        llm_model, approved_by, confidence, notes,
        )`,

    webhook: `# main.py (Ausschnitt)
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from graph.agent import build_graph

app = FastAPI()
graph = None  # initialisiert beim Start

@app.on_event("startup")
async def startup():
    global graph
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    import asyncpg
    pool = await asyncpg.create_pool(settings.database_url)
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    graph = build_graph(checkpointer)
    # Startup-Nachricht
    await send_message("🟢 FRYA Agent gestartet.")

@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.llm_provider}

@app.post("/webhook/document")
async def document_webhook(request: Request, background: BackgroundTasks):
    """Paperless ruft diesen Endpoint auf nach Dokument-Verarbeitung."""
    body = await request.json()
    doc_id = body.get("document_id")
    background.add_task(process_document, doc_id)
    return JSONResponse({"status": "queued", "doc_id": doc_id})

async def process_document(doc_id: int):
    config = {"configurable": {"thread_id": settings.telegram_chat_id}}
    await graph.ainvoke(
        {"messages": [{"role": "system", "content": f"document_webhook:{doc_id}"}]},
        config=config
    )

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    """Telegram sendet eingehende Nachrichten hier rein."""
    body = await request.json()
    background.add_task(process_telegram, body)
    return JSONResponse({"status": "ok"})`,
  };

  return (
    <div>
      <SectionTitle>FRYA Agent — Exakter Code (Stage 1)</SectionTitle>
      <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
        {sections.map(s => (
          <button key={s.id} onClick={() => setSection(s.id)} style={{
            background: section === s.id ? C.purpleDim : C.surface,
            color: section === s.id ? C.purple : C.textDim,
            border: `1px solid ${section === s.id ? C.purple : C.border}`,
            borderRadius: 6, padding: "6px 12px", fontSize: 11, cursor: "pointer", fontFamily: "monospace",
          }}>{s.label}</button>
        ))}
      </div>
      <Code>{content[section]}</Code>
      <Box color={C.green} bg="#0a1a0a" style={{ marginTop: 12 }}>
        <div style={{ fontSize: 11, color: C.green, fontFamily: "monospace" }}>requirements.txt</div>
        <Code>{`fastapi==0.115.*
uvicorn[standard]==0.34.*
litellm==1.56.*          # LLM-agnostisch — alle Provider
langgraph==0.2.*         # Stateful Agent Graph
langchain-core==0.3.*
asyncpg==0.30.*          # PostgreSQL async
pydantic-settings==2.7.*
httpx==0.28.*
python-telegram-bot==21.* # Optional, oder direkt HTTP nutzen`}</Code>
      </Box>
    </div>
  );
}

// ─── APP TAB ──────────────────────────────────────────────────────────────────
function AppTab() {
  return (
    <div>
      <SectionTitle>Android App — Architektur (Flutter)</SectionTitle>
      <Box color={C.accent} bg={C.accentDim + "44"} style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.accent, marginBottom: 8 }}>3 Screens, 2 Backend-Verbindungen</div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {[
            { screen: "💬 Chat Screen", desc: "WebSocket/SSE zum FRYA Agent\nNachrichten senden/empfangen\nInline-Buttons (Approve/Reject)\nDokument-Thumbnails aus Paperless", color: C.accent },
            { screen: "📷 Scanner Screen", desc: "ML Kit Document Scanner\nCrop + Enhance\nDirekt POST an Paperless API\n/api/documents/post_document/", color: C.green },
            { screen: "📄 Dokument Viewer", desc: "GET Paperless API\nPDF in-app rendern\nDownload speichern\nVom Agent gesendete Links öffnen", color: C.purple },
          ].map(s => (
            <Box key={s.screen} color={s.color} bg={s.color + "11"} style={{ flex: 1, minWidth: 180 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: s.color, marginBottom: 6 }}>{s.screen}</div>
              <div style={{ fontSize: 11, color: C.textDim, whiteSpace: "pre-line" }}>{s.desc}</div>
            </Box>
          ))}
        </div>
      </Box>

      <Box style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 12, color: C.accent, fontFamily: "monospace", marginBottom: 8 }}>Backend-Verbindungen der App</div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Box color={C.purple} bg={C.purpleDim + "44"} style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.purple }}>FRYA Agent API</div>
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 4 }}>
              https://agent.staging.myfrya.de<br/>
              POST /webhook/telegram (Nachrichten)<br/>
              GET /sse/chat (Server-Sent Events)<br/>
              Auth: FRYA_APP_TOKEN
            </div>
          </Box>
          <Box color={C.green} bg={C.greenDim + "44"} style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.green }}>Paperless API (direkt)</div>
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 4 }}>
              https://paperless.staging.myfrya.de<br/>
              POST /api/documents/post_document/ (Upload)<br/>
              GET /api/documents/{"{id}"}/download/ (Viewer)<br/>
              Auth: API Token
            </div>
          </Box>
        </div>
      </Box>

      <Code>{`# pubspec.yaml (wichtige Dependencies)
dependencies:
  flutter:
    sdk: flutter
  http: ^1.2.0
  web_socket_channel: ^2.4.0   # Agent Chat
  camera: ^0.10.5              # Scanner
  google_mlkit_document_scanner: ^0.1.0  # ML Kit
  syncfusion_flutter_pdfviewer: ^26.1.0  # PDF Viewer
  file_picker: ^8.0.0
  shared_preferences: ^2.2.3   # Token Storage
  flutter_secure_storage: ^9.0.0

# lib/services/agent_service.dart
class AgentService {
  final String baseUrl;
  final String token;
  WebSocketChannel? _channel;

  Stream<String> connectChat(String chatId) {
    _channel = WebSocketChannel.connect(
      Uri.parse('\$baseUrl/ws/chat/\$chatId?token=\$token'),
    );
    return _channel!.stream.map((e) => e.toString());
  }

  Future<void> sendMessage(String text) async {
    _channel?.sink.add(jsonEncode({'type': 'message', 'text': text}));
  }

  Future<void> sendApproval(String docId, String action) async {
    // action: 'approve' | 'reject' | 'edit'
    _channel?.sink.add(jsonEncode({'type': 'approval', 'doc_id': docId, 'action': action}));
  }
}

# lib/services/paperless_service.dart
class PaperlessService {
  Future<void> uploadDocument(File file, List<int> tags) async {
    final request = http.MultipartRequest(
      'POST', Uri.parse('\$paperlessUrl/api/documents/post_document/'),
    );
    request.headers['Authorization'] = 'Token \$token';
    request.files.add(await http.MultipartFile.fromPath('document', file.path));
    request.fields['tags'] = tags.join(',');
    await request.send();
  }

  Future<Uint8List> downloadDocument(int docId) async {
    final response = await http.get(
      Uri.parse('\$paperlessUrl/api/documents/\$docId/download/'),
      headers: {'Authorization': 'Token \$token'},
    );
    return response.bodyBytes;
  }
}`}</Code>

      <Box color={C.warn} bg={C.warnDim + "55"}>
        <div style={{ fontSize: 12, color: C.warn, fontWeight: 700, marginBottom: 6 }}>📌 Deine bestehende App — Was davon nutzen</div>
        <div style={{ fontSize: 12, color: C.textDim, lineHeight: 1.8 }}>
          Du hast bereits einen Android ML Kit Scanner eingebaut. Das ist genau richtig — <strong style={{ color: C.text }}>behalten und ausbauen.</strong><br/>
          Was fehlt: Chat-Screen mit Agent WebSocket, Dokument-Viewer (PDF), Auth-Screen für beide APIs.<br/>
          Der ML Kit Scanner → Upload Flow ist der wichtigste Teil. Den hast du schon. Gut.
        </div>
      </Box>
    </div>
  );
}

// ─── PAPERLESS TAB ────────────────────────────────────────────────────────────
function PaperlessTab() {
  return (
    <div>
      <SectionTitle>Paperless Setup — Alles konfigurieren bevor Agent startet</SectionTitle>
      <Box color={C.green} bg="#0a1a0a" style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.green, marginBottom: 8 }}>1. Environment-Variablen (compose.yml / .env)</div>
        <Code>{`# .env Ergänzungen für Paperless
PAPERLESS_AUDIT_LOG_ENABLED=true
PAPERLESS_OCR_LANGUAGE=deu+eng    # Deutsch + Englisch
PAPERLESS_FILENAME_FORMAT={created_year}/{correspondent}/{title}
PAPERLESS_CONSUMER_RECURSIVE=true
PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS=true`}</Code>
      </Box>

      <Box style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.accent, marginBottom: 8 }}>2. Custom Fields anlegen (via Web UI oder API)</div>
        <Code>{`# POST https://paperless.staging.myfrya.de/api/custom_fields/
# Header: Authorization: Token <TOKEN>

# Feld 1
{"name": "Buchungsstatus", "data_type": "select",
 "extra_data": {"select_options": ["zu-buchen", "gebucht", "abgelehnt", "manuell"]}}

# Feld 2
{"name": "Rechnungsbetrag Brutto", "data_type": "monetary"}

# Feld 3
{"name": "Rechnungsbetrag Netto",  "data_type": "monetary"}

# Feld 4
{"name": "MwSt Betrag",            "data_type": "monetary"}

# Feld 5
{"name": "Fälligkeitsdatum",       "data_type": "date"}

# Feld 6
{"name": "IBAN Lieferant",         "data_type": "string"}

# Feld 7
{"name": "Rechnungsnummer",        "data_type": "string"}`}</Code>
      </Box>

      <Box style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.accent, marginBottom: 8 }}>3. Tags anlegen</div>
        <Code>{`# Tags die der Agent setzt:
zu-buchen        # Wartet auf Buchungsvorschlag
gebucht          # Buchung erfolgt in Akaunting
abgelehnt        # User hat abgelehnt
manuell-prüfen   # Konfidenz zu niedrig, manuell ansehen

# Tags für paperless-gpt:
paperless-gpt-auto    # Trigger für LLM-Verarbeitung (auto gesetzt via Workflow)
gpt-processed         # paperless-gpt hat das Dokument verarbeitet (gesetzt von gpt)`}</Code>
      </Box>

      <Box style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, color: C.accent, marginBottom: 8 }}>4. Workflows anlegen (Paperless Web UI → Settings → Workflows)</div>
        <Code>{`# Workflow 1: "AI-Tag setzen"
Trigger:  Document Added
Filters:  (keine — alle neuen Dokumente)
Action:   Add Tag → paperless-gpt-auto

# Workflow 2: "Agent benachrichtigen"
Trigger:  Document Updated
Filters:  Tag = gpt-processed
Action:   Webhook → POST https://agent.staging.myfrya.de/webhook/document
          Body: {"document_id": "{{ document.id }}"}

# Workflow 3: "Upload-Quelle tracken"
Trigger:  Consumption Started
Filters:  Source = API (App-Uploads)
Action:   Add Tag → via-app`}</Code>
      </Box>

      <Box color={C.warn} bg={C.warnDim + "55"}>
        <div style={{ fontWeight: 700, color: C.warn, marginBottom: 6 }}>⚠ Wichtig: Webhook-URL muss von paperless-ngx erreichbar sein</div>
        <Code>{`# paperless-ngx → agent sind im selben Docker-Netzwerk (frya-internal)
# Deshalb INTERNE URL verwenden:
# Webhook URL = http://frya-agent:8001/webhook/document
# NICHT die externe Traefik-URL!`}</Code>
      </Box>
    </div>
  );
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
export default function FryaStage1() {
  const [tab, setTab] = useState("sprint");
  const tabs = { sprint: <SprintTab />, server: <ServerTab />, agent: <AgentTab />, app: <AppTab />, paperless: <PaperlessTab /> };

  return (
    <div style={{ background: C.bg, color: C.text, fontFamily: "'Fira Code', 'SF Mono', monospace", minHeight: "100vh" }}>
      <div style={{ background: C.surface, borderBottom: `1px solid ${C.border}`, padding: "14px 24px", display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <div>
          <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: 2, color: C.accent }}>FRYA</span>
          <span style={{ fontSize: 11, color: C.muted, letterSpacing: 1, marginLeft: 12 }}>STAGE 1 BUILD PLAN — Paperless + Agent + App</span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Chip color={C.greenDim} text={C.green}>~10 Tage</Chip>
          <Chip color={C.purpleDim} text={C.purple}>LangGraph</Chip>
          <Chip color={C.accentDim} text={C.accent}>LiteLLM</Chip>
          <Chip color={C.redDim} text={C.red}>n8n raus</Chip>
        </div>
      </div>
      <div style={{ display: "flex", borderBottom: `1px solid ${C.border}`, background: C.surface, overflowX: "auto" }}>
        {TAB.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{ background: "transparent", border: "none", borderBottom: `2px solid ${tab === t.id ? C.accent : "transparent"}`, color: tab === t.id ? C.accent : C.textDim, padding: "12px 18px", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap", fontFamily: "'Fira Code', monospace" }}>{t.label}</button>
        ))}
      </div>
      <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>{tabs[tab]}</div>
    </div>
  );
}
