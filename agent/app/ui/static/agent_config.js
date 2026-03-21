/* agent_config.js — CSP-compliant, single-dropdown model selection */
(function () {
  'use strict';

  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var HDR = {'Content-Type': 'application/json', 'X-Frya-Csrf-Token': CSRF};

  function getCard(el) {
    return el.closest('.agent-card');
  }

  function getAgentId(card) {
    return card.getAttribute('data-agent-id');
  }

  /* Model dropdown change — show/hide custom fields, update hidden inputs */
  function onModelSelectChange(selectEl) {
    var card = getCard(selectEl);
    var customFields = card.querySelector('.custom-fields');
    var hiddenProvider = card.querySelector('input[type="hidden"].cfg-provider');
    var hiddenModel = card.querySelector('input[type="hidden"].cfg-model');
    var hiddenBaseUrl = card.querySelector('input[type="hidden"].cfg-base-url');
    var opt = selectEl.options[selectEl.selectedIndex];

    if (selectEl.value === 'custom') {
      customFields.style.display = 'block';
    } else {
      customFields.style.display = 'none';
      if (hiddenProvider) hiddenProvider.value = opt.getAttribute('data-provider') || '';
      if (hiddenModel) hiddenModel.value = opt.getAttribute('data-model') || '';
      if (hiddenBaseUrl) hiddenBaseUrl.value = opt.getAttribute('data-base-url') || '';
    }
  }

  /* Save config */
  async function saveConfig(card) {
    var agentId = getAgentId(card);
    var btn = card.querySelector('.btn-save');
    btn.disabled = true;
    btn.textContent = '...';
    try {
      var selectEl = card.querySelector('.cfg-model-select');
      var isCustom = selectEl && selectEl.value === 'custom';
      var provider, model, base_url, api_key;

      if (isCustom) {
        var cf = card.querySelector('.custom-fields');
        provider = cf.querySelector('.cfg-provider').value;
        model = cf.querySelector('.cfg-model').value;
        base_url = cf.querySelector('.cfg-base-url').value;
        api_key = cf.querySelector('.cfg-api-key').value;
      } else {
        provider = card.querySelector('input[type="hidden"].cfg-provider').value;
        model = card.querySelector('input[type="hidden"].cfg-model').value;
        base_url = card.querySelector('input[type="hidden"].cfg-base-url').value;
        api_key = '';
      }

      var body = {provider: provider, model: model, base_url: base_url, api_key: api_key};
      var resp = await fetch('/api/agent-config/' + agentId, {
        method: 'POST', headers: HDR, body: JSON.stringify(body),
      });
      var data = await resp.json();
      if (!resp.ok) {
        alert('Fehler: ' + (data.detail || resp.status));
        return;
      }
      btn.textContent = 'Gespeichert!';
      // Auto-check after save to verify model swap
      setTimeout(function () { checkHealth(card); }, 500);
      if (data.api_key_set && isCustom) {
        var keyInput = card.querySelector('.custom-fields .cfg-api-key');
        if (keyInput) {
          keyInput.placeholder = '(gesetzt)';
          keyInput.value = '';
        }
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
        badge.textContent = 'Getestet \u2014 ' + (data.actual_model || data.configured_model || '?') + ' (' + data.response_time_ms + 'ms)';
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
    if (e.target.classList.contains('cfg-model-select')) {
      onModelSelectChange(e.target);
    }
  });
})();
