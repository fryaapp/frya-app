#!/bin/bash
# Paperless post-consume script — calls FRYA backend webhook
# Env vars provided by Paperless: DOCUMENT_ID, DOCUMENT_TITLE, etc.
FRYA_WEBHOOK_URL="http://backend:8001/webhooks/paperless/document"
PAYLOAD="{\"document_id\": \"${DOCUMENT_ID}\", \"title\": \"${DOCUMENT_TITLE}\", \"original_file_name\": \"${DOCUMENT_ORIGINAL_FILENAME}\", \"created\": \"${DOCUMENT_CREATED}\", \"added\": \"${DOCUMENT_ADDED}\"}"
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$FRYA_WEBHOOK_URL" \
  --max-time 30 \
  >> /tmp/frya_webhook.log 2>&1
exit 0
