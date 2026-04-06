# Upload Progress Plan

## Aktueller Flow (was gefunden wurde)

### Frontend
- `ChatInputBar.tsx`: Hauptkomponente für Upload. Nutzt `api.postFormData('/documents/bulk-upload', form)`.
  Setzt lokalen State `uploading=true/false`, zeigt nur ein Sanduhr-Icon im Button.
  Zeigt nach Upload eine statische Frya-Nachricht: "Alles klar! X Belege empfangen."
- `ChatView.tsx`: Drag-&-Drop-Zone, ebenfalls `api.postFormData('/documents/bulk-upload', form)`,
  gleiche statische Nachricht ohne Progress.
- `fryaStore.ts`: Bekannte WS-Types: pong, typing, chunk, message_complete, approval_request,
  notification, duplicate, ui_hint, error.
  KEIN `upload_progress` vorhanden.
  Es gibt `document_processed` als notification_type (vom Backend nach Paperless-Webhook).
- `ChatHistory.tsx`: Rendert `ChatMessage`-Komponenten aus dem Store.
- `ChatMessage.tsx`: Rendert User/Frya/System-Nachrichten. System-Nachrichten ohne
  `approval`/`duplicate` werden als normaler Text gezeigt.

### Backend
- `bulk_upload.py` (`POST /api/v1/documents/bulk-upload`): Verarbeitet Upload synchron,
  gibt sofort `{batch_id, status: 'processing'}` zurück. Kein WS-Push während Upload.
- `chat_ws.py`: `_ChatConnectionRegistry` mit `broadcast()` und `send_to_user(user_id, msg)`.
  Wird von Paperless-Webhook (webhooks.py) genutzt, um `document_processed` zu pushen.
- `webhooks.py`: Sendet nach Paperless-Verarbeitung `notification/document_processed` per
  `chat_registry.broadcast()`.

## Analyse: Architektur-Herausforderung

Der Upload-Flow ist **asynchron und zweistufig**:
1. `POST /bulk-upload` → Datei landet bei Paperless (schnell, <5s)
2. Paperless verarbeitet OCR+Analyse → Webhook → `chat_registry.broadcast(document_processed)` (langsam, 30-120s)

Zwischen Schritt 1 und 2 hat das Backend KEINEN Mechanismus, um Status-Updates zu senden.
Der `send_to_user(user_id, ...)` in `chat_registry` ist vorhanden, wird aber im Upload-Pfad
nicht genutzt.

## Geplante Änderungen Frontend

### Datei: `ui/src/stores/fryaStore.ts`
- Neuen WS-Type `upload_progress` in `WsMessageIncoming` hinzufügen
- Handler im `switch`-Block: legt eine spezielle Progress-Message in `messages` an
  (role: 'system', progressType: 'upload_progress')
- Neues Feld `uploadProgress` im `ChatMessage`-Interface (optional)

### Datei: `ui/src/components/chat/ChatInputBar.tsx`
- Während Upload: direkt nach `api.postFormData()` eine Progress-Nachricht in den Store
  einfügen, die den Upload-Fortschritt zeigt (Stufe "uploading" → "ocr" via WS).
- Initial-Stage "uploading" wird sofort lokal gesetzt (kein WS nötig).

### Datei: `ui/src/components/chat/ChatMessage.tsx`
- Neuer Render-Pfad für `uploadProgress`-Messages: zeigt die Fortschrittsanzeige-Card.

## Geplante Änderungen Backend

### Datei: `agent/app/api/bulk_upload.py`
- Nach erfolgreichem Paperless-Upload (`task_id` vorhanden):
  `chat_registry.send_to_user(user_id, {type: 'upload_progress', filename, stage: 'ocr', percent: 60})`
  senden. Dafür wird `user_id` aus dem `current_user`-Objekt genutzt.

### Datei: `agent/app/api/webhooks.py`
- Nach bestehendem `document_processed`-Broadcast zusätzlich:
  `{type: 'upload_progress', stage: 'done', percent: 100}` broadcasten.

## Implementierungsstrategie (gewählt)

Da Backend-seitige Stage-Übergänge (uploading→ocr→analysis→done) keine echten Hooks haben
(Paperless-OCR ist eine Blackbox), wird eine **Frontend-simulierte Progress-Bar** mit
einem WS-Hook am Ende implementiert:

1. **Sofort beim Upload-Start**: Frya-Nachricht wird durch eine Progress-Card ersetzt
   (stage: "uploading", 30%)
2. **Nach API-Antwort** (Paperless hat Datei): stage "ocr", 60% (lokal, kein WS)
3. **Bei `document_processed` WS-Event**: Progress-Card auf "done" 100% aktualisieren,
   dann nach 2s durch normale Frya-Nachricht ersetzen

Dies braucht KEINEN Backend-Umbau. Das `document_processed`-Event existiert bereits.

## Entscheidung: Implementierbar? JA

**Begründung**:
- Nur Frontend-Änderungen nötig (3 Dateien: fryaStore.ts, ChatInputBar.tsx, ChatMessage.tsx)
- Kein neuer WS-Type im Backend erforderlich — `document_processed` reicht als "done"-Signal
- Aufwand ~2h, gut unter der 3h-Grenze
- Kein neues File nötig (nur edits an bestehenden Dateien)
- Sauber in die bestehende ChatMessage-Architektur integrierbar
