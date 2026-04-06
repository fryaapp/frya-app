# PLAN: Aktenordner-Feature

Datum: 2026-04-06
Status: Entwurf

---

## Konzept

Der User kann Frya bitten, thematische Aktenordner anzulegen, die Dokumente automatisch nach inhaltlichen Kriterien zusammenfassen.

**Ablauf (Beispiel):**

1. User sagt: "Erstelle einen Ordner Hausbau"
2. Frya fragt nach: "Welche Art von Dokumenten sollen in diesen Ordner? Beschreibe kurz die Kriterien."
3. User beschreibt: "Alles was mit dem Hausbau zu tun hat — Handwerker, Baumaterial, Finanzierung"
4. Frya erstellt den Ordner mit den hinterlegten Filterkriterien und weist automatisch passende vorhandene Dokumente zu.
5. Neue Dokumente werden beim Eingang semantisch klassifiziert und ggf. einem Ordner zugeordnet.

---

## Datenbankstruktur

```sql
CREATE TABLE frya_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    filter_criteria JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**filter_criteria-Schema (JSONB):**

```json
{
  "keywords": ["Handwerker", "Baumaterial", "Finanzierung", "Baukredit"],
  "categories": ["Rechnung", "Vertrag", "Angebot"],
  "tags": ["hausbau"],
  "match_mode": "any"
}
```

---

## API-Endpoints

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| POST | `/api/v1/folders` | Neuen Ordner erstellen |
| GET | `/api/v1/folders` | Alle Ordner des Tenants abrufen |
| GET | `/api/v1/folders/{id}/documents` | Dokumente im Ordner abrufen |
| DELETE | `/api/v1/folders/{id}` | Ordner loeschen |

### POST /api/v1/folders — Request-Body

```json
{
  "name": "Hausbau",
  "description": "Alles rund um den Hausbau",
  "filter_criteria": {
    "keywords": ["Handwerker", "Baumaterial", "Finanzierung"],
    "match_mode": "any"
  }
}
```

---

## Communicator-Integration

Der Communicator benoetigt einen neuen Prompt-Baustein, der:

1. Erkennt, wenn der User einen Ordner anlegen moechte (Intent: `create_folder`)
2. Die Rueckfrage nach Kriterien stellt
3. Nach Bestaetigung den POST-Endpoint aufruft
4. Dem User eine Zusammenfassung der automatischen Zuordnung gibt

**Neuer Intent im Communicator:**

```python
"create_folder": {
    "description": "User moechte einen thematischen Aktenordner erstellen",
    "follow_up": "Welche Art von Dokumenten sollen in diesen Ordner? Beschreibe die Themen oder Stichworte.",
    "action": "POST /api/v1/folders"
}
```

---

## Automatische Zuordnung

Beim Erstellen eines Ordners laeuft im Hintergrund:

1. Alle vorhandenen Dokumente des Tenants werden gegen `filter_criteria` geprueft
2. Treffer werden als `folder_assignments` gespeichert (eigene Tabelle oder JSONB in `frya_folders`)
3. Bei neuen Uploads wird nach OCR/Klassifizierung ebenfalls gegen alle Ordner geprueft

**Optionale Erweiterungstabelle:**

```sql
CREATE TABLE frya_folder_assignments (
    folder_id UUID REFERENCES frya_folders(id) ON DELETE CASCADE,
    document_id UUID NOT NULL,
    confidence FLOAT,
    assigned_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (folder_id, document_id)
);
```

---

## Aufwand-Schaetzung

| Bereich | Aufwand | Inhalt |
|---------|---------|--------|
| Backend | 1 Session | Tabellen, Endpoints, automatische Zuordnung |
| Frontend | 1 Session | Ordner-Liste, Ordner-Detail mit Dokumenten, Loeschen |
| Communicator | Prompt-Update | Intent-Erkennung, Rueckfrage, Action-Aufruf |
| Gesamt | 2-3 Sessions | |

---

## Offene Fragen

- Sollen Ordner editierbar sein (Kriterien nachtraeglich aendern)?
- Manuelle Zuordnung zusaetzlich zur automatischen?
- Verschachtelung (Unterordner) in Phase 1 oder erst spaeter?
- Notification wenn neue Dokumente automatisch zugeordnet werden?
