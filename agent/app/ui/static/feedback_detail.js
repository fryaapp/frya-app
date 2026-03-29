/* feedback_detail.js — Status update for feedback detail page */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('btn-status');
    if (!btn) return;

    btn.addEventListener('click', async function() {
      var select = document.getElementById('status-select');
      var msg = document.getElementById('status-msg');
      var feedbackId = btn.dataset.feedbackId;
      if (!feedbackId || !select) return;

      try {
        var resp = await fetch('/ui/feedback/' + feedbackId + '/status', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: select.value }),
          credentials: 'include',
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        if (msg) { msg.textContent = 'Gespeichert!'; msg.style.color = 'green'; }
        setTimeout(function() { location.reload(); }, 1000);
      } catch (e) {
        if (msg) { msg.textContent = 'Fehler: ' + e.message; msg.style.color = 'red'; }
      }
    });
  });
})();
