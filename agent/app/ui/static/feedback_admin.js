/* feedback_admin.js — Feedback listing: checkboxes, export, row click */
(function () {
  'use strict';

  function updateCount() {
    var checked = document.querySelectorAll('.fb-check:checked');
    var btn = document.getElementById('btn-export');
    if (btn) {
      btn.textContent = 'Markierte exportieren (' + checked.length + ')';
      btn.disabled = checked.length === 0;
    }
  }

  function toggleAll(state) {
    var boxes = document.querySelectorAll('.fb-check');
    if (state === undefined || state === null) {
      var anyChecked = document.querySelectorAll('.fb-check:checked').length > 0;
      boxes.forEach(function(b) { b.checked = !anyChecked; });
    } else {
      boxes.forEach(function(b) { b.checked = state; });
    }
    updateCount();
  }

  async function exportSelected() {
    var ids = Array.from(document.querySelectorAll('.fb-check:checked')).map(function(c) { return c.value; });
    if (ids.length === 0) return;

    var btn = document.getElementById('btn-export');
    var status = document.getElementById('export-status');
    btn.disabled = true;
    btn.textContent = 'Exportiere...';

    try {
      var resp = await fetch('/ui/feedback/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback_ids: ids }),
        credentials: 'include',
      });

      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      // PDF Download (Backend liefert application/pdf)
      var blob = await resp.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'frya-bugreport-' + new Date().toISOString().slice(0, 10) + '.pdf';
      a.click();
      URL.revokeObjectURL(url);

      if (status) {
        status.textContent = ids.length + ' Bug(s) als PDF exportiert';
        status.style.color = 'green';
      }

      setTimeout(function() { location.reload(); }, 2000);
    } catch (e) {
      if (status) {
        status.textContent = 'Export fehlgeschlagen: ' + e.message;
        status.style.color = 'red';
      }
      btn.disabled = false;
      updateCount();
    }
  }

  // Bind events on DOMContentLoaded
  document.addEventListener('DOMContentLoaded', function() {
    // Checkbox change + click handlers
    document.querySelectorAll('.fb-check').forEach(function(cb) {
      cb.addEventListener('change', updateCount);
      // Stop click from bubbling to tr row-click handler
      cb.addEventListener('click', function(e) { e.stopPropagation(); });
    });

    // Header checkbox
    var checkAll = document.getElementById('check-all');
    if (checkAll) {
      checkAll.addEventListener('change', function() { toggleAll(this.checked); });
    }

    // Export button
    var btnExport = document.getElementById('btn-export');
    if (btnExport) {
      btnExport.addEventListener('click', exportSelected);
    }

    // Toggle all button
    var btnToggle = document.getElementById('btn-toggle-all');
    if (btnToggle) {
      btnToggle.addEventListener('click', function() { toggleAll(); });
    }

    // Row clicks (navigate to detail) — skip if clicking checkbox or its <td>
    document.querySelectorAll('tr[data-feedback-id]').forEach(function(row) {
      row.style.cursor = 'pointer';
      row.addEventListener('click', function(e) {
        // Skip if clicking checkbox or the td containing it
        var t = e.target;
        if (t.type === 'checkbox' || t.tagName === 'INPUT') return;
        if (t.tagName === 'TD' && t.querySelector('input[type="checkbox"]')) return;
        window.location = '/ui/feedback/' + row.dataset.feedbackId;
      });
    });
  });
})();
