# FRYA UI — Deploy-Anleitung

## Voraussetzungen

- Node.js 18+ lokal
- SSH-Zugang zu `frya-staging` (Server)
- Docker + Traefik v3 auf dem Server
- Netzwerk `frya-internal` existiert (`docker network create frya-internal`)

## 1. Lokal: Build erstellen

```bash
cd "C:\Users\lenovo\Documents\Frya App\ui"
npm install
npm run build
```

Build-Output liegt in `ui/dist/`.

## 2. Auf Server hochladen

```bash
cd "C:\Users\lenovo\Documents\Frya App"

# Build-Artifacts packen
tar czf frya-ui-dist.tar.gz -C ui/dist .

# Hochladen
scp frya-ui-dist.tar.gz frya-staging:/opt/dms-staging/ui/
scp ui/nginx.conf frya-staging:/opt/dms-staging/ui/
scp docker-compose.ui.yml frya-staging:/opt/dms-staging/
```

## 3. Auf Server: Entpacken + Starten

```bash
ssh frya-staging << 'EOF'
cd /opt/dms-staging
mkdir -p ui/dist
cd ui && tar xzf frya-ui-dist.tar.gz -C dist && rm frya-ui-dist.tar.gz
cd ..
docker compose -f docker-compose.ui.yml up -d
docker compose -f docker-compose.ui.yml logs --tail 20
EOF
```

## 4. Prüfen

```bash
# Container läuft?
ssh frya-staging "docker ps | grep frya-ui"

# UI erreichbar?
curl -I https://staging.myfrya.de

# API-Proxy funktioniert?
curl -I https://staging.myfrya.de/api/v1/health
```

## Re-Deploy (nur UI-Änderungen)

```bash
cd "C:\Users\lenovo\Documents\Frya App\ui"
npm run build
tar czf frya-ui-dist.tar.gz -C dist .
scp frya-ui-dist.tar.gz frya-staging:/opt/dms-staging/ui/
ssh frya-staging "cd /opt/dms-staging/ui && tar xzf frya-ui-dist.tar.gz -C dist && rm frya-ui-dist.tar.gz && docker restart frya-ui"
```

## Nginx-Config ändern

```bash
scp ui/nginx.conf frya-staging:/opt/dms-staging/ui/
ssh frya-staging "docker restart frya-ui"
```
