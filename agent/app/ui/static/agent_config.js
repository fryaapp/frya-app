/* agent_config.js — CSP-compliant (no inline scripts) */
(function () {
  'use strict';

  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var HDR = {'Content-Type': 'application/json', 'X-Frya-Csrf-Token': CSRF};
  var IONOS_BASE_URL = 'https://openai.inference.de-txl.ionos.com/v1';

  function getCard(el) {
    return el.closest('.agent-card');
  }

  function getAgentId(card) {
    return card.getAttribute('data-agent-id');
  }

  /* Provider change — auto-fill IONOS base URL */
  function onProviderChange(selectEl) {
    var card = getCard(selectEl);
    var baseUrlInput = card.querySelector('.cfg-base-url');
    var modelInput = card.querySelector('.cfg-model');
    if (selectEl.value === 'ionos') {
      if (!baseUrlInput.value) {
        baseUrlInput.value = IONOS_BASE_URL;
      }
      modelInput.placeholder = 'z.B. meta-llama/Llama-3.3-70B-Instruct';
    } else if (baseUrlInput.value === IONOS_BASE_URL) {
      baseUrlInput.value = '';
      modelInput.placeholder = 'z.B. gpt-4o-mini';
    }
  }

  /* Save config */
  async function saveConfig(card) {
    var agentId = getAgentId(card);
    var btn = card.querySelector('.btn-save');
    btn.disabled = true;
    btn.textContent = '...';
    try {
      var body = {
        provider: card.querySelector('.cfg-provider').value,
        model: card.querySelector('.cfg-model').value,
        api_key: card.querySelector('.cfg-api-key').value,
        base_url: card.querySelector('.cfg-base-url').value,
      };
      var resp = await fetch('/api/agent-config/' + agentId, {
        method: 'POST', headers: HDR, body: JSON.stringify(body),
      });
      var data = await resp.json();
      if (!resp.ok) {
        alert('Fehler: ' + (data.detail || resp.status));
        return;
      }
      btn.textContent = 'Gespeichert!';
      if (data.api_key_set) {
        card.querySelector('.cfg-api-key').placeholder = '(gesetzt)';
        card.querySelector('.cfg-api-key').value = '';
      }
    } catch (e) {
      alert('Netzwerkfehler: ' + e);
    } finally {
      setTimeout(function () { btn.disabled = false; btn.textContent = 'Speichern'; }, 1500);
    }
  }

  /* Health check */
  async function checkHealth(card) {
    var agentId = getAgentId(card);
    var btn = card.querySelector('.btn-check');
    var badge = card.querySelector('.state-badge');
    var detail = card.querySelector('.health-detail');
    btn.disabled = true;
    btn.textContent = 'Pruefe...';
    badge.className = 'state-badge';
    badge.textContent = 'Pruefe...';
    try {
      var resp = await fetch('/api/agent-config/' + agentId + '/check', {
        method: 'POST', headers: HDR,
      });
      var data = await resp.json();
      if (!resp.ok) {
        badge.className = 'state-badge state-error';
        badge.textContent = 'Fehler';
        detail.textContent = data.detail || resp.status;
        return;
      }
      if (data.status.startsWith('ok')) {
        badge.className = 'state-badge state-ok';
        badge.textContent = 'Aktiv \u2014 ' + card.querySelector('.cfg-model').value;
      } else {
        badge.className = 'state-badge state-error';
        badge.textContent = 'Fehler';
      }
      detail.textContent = data.status;
    } catch (e) {
      badge.className = 'state-badge state-error';
      badge.textContent = 'Netzwerkfehler';
      detail.textContent = String(e);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Jetzt pruefen';
    }
  }

  /* Event delegation */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var card = getCard(btn);
    if (!card) return;
    var action = btn.getAttribute('data-action');
    if (action === 'save') saveConfig(card);
    else if (action === 'check') checkHealth(card);
  });

  document.addEventListener('change', function (e) {
    if (e.target.classList.contains('cfg-provider')) {
      onProviderChange(e.target);
    }
  });
})();
