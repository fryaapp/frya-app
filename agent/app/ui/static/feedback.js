/* feedback.js — Alpha feedback button (CSP-compliant) */
(function () {
  'use strict';

  var btn = document.createElement('button');
  btn.id = 'frya-feedback-btn';
  btn.title = 'Problem melden';
  btn.textContent = '!';
  btn.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;background:#e74c3c;color:#fff;border:none;border-radius:50%;width:48px;height:48px;font-size:22px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,0.3);';
  document.body.appendChild(btn);

  var overlay = document.createElement('div');
  overlay.id = 'frya-feedback-overlay';
  overlay.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;';
  overlay.innerHTML =
    '<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;padding:24px;border-radius:8px;width:400px;max-width:90vw;">' +
    '<h3 style="margin:0 0 12px">Problem melden</h3>' +
    '<textarea id="fb-desc" rows="4" style="width:100%;box-sizing:border-box;margin-bottom:8px;" placeholder="Was ist das Problem?"></textarea>' +
    '<div style="display:flex;gap:8px;justify-content:flex-end;">' +
    '<button id="fb-cancel" style="padding:6px 16px;cursor:pointer;">Abbrechen</button>' +
    '<button id="fb-send" style="padding:6px 16px;background:#059669;color:#fff;border:none;border-radius:4px;cursor:pointer;">Senden</button>' +
    '</div></div>';
  document.body.appendChild(overlay);

  btn.addEventListener('click', function () {
    overlay.style.display = 'block';
    document.getElementById('fb-desc').value = '';
    document.getElementById('fb-desc').focus();
  });

  document.getElementById('fb-cancel').addEventListener('click', function () {
    overlay.style.display = 'none';
  });

  document.getElementById('fb-send').addEventListener('click', async function () {
    var desc = document.getElementById('fb-desc').value.trim();
    if (!desc) return;
    var sendBtn = document.getElementById('fb-send');
    sendBtn.disabled = true;
    sendBtn.textContent = '...';
    try {
      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var headers = {'X-Frya-Csrf-Token': csrfMeta ? csrfMeta.content : ''};
      var fd = new FormData();
      fd.append('description', desc);
      fd.append('page', window.location.pathname);
      var resp = await fetch('/api/v1/feedback', {method: 'POST', headers: headers, body: fd});
      if (resp.ok) {
        overlay.style.display = 'none';
        btn.textContent = '\u2713';
        btn.style.background = '#059669';
        setTimeout(function () { btn.textContent = '!'; btn.style.background = '#e74c3c'; }, 3000);
      } else {
        var data = await resp.json().catch(function () { return {}; });
        alert('Fehler: ' + (data.detail || resp.status));
      }
    } catch (e) {
      alert('Netzwerkfehler: ' + e);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Senden';
    }
  });
})();
