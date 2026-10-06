// Refresh read-only status. Never reload the page or touch form values.
(() => {
  const status = document.getElementById("automation-title");
  const warning = document.getElementById("status-refresh-error");
  if (!status || !warning) return;
  const pauseDialog = document.getElementById('pause-confirmation');
  const pauseForm = document.querySelector('[data-control="pause"]');
  if (pauseDialog && typeof pauseDialog.showModal === 'function') {
    pauseForm.addEventListener('submit', event => {
      event.preventDefault();
      pauseDialog.showModal();
      pauseDialog.querySelector('[data-cancel-pause]').focus();
    });
    pauseDialog.querySelector('[data-cancel-pause]').addEventListener('click', event => {
      event.preventDefault();
      pauseDialog.close();
    });
    pauseDialog.addEventListener('close', () => pauseForm.querySelector('button').focus());
  }
  let fetching = false;
  const gmailConnection = document.getElementById('gmail-connection');
  const gmailLabel = document.getElementById('gmail-connection-label');

  function updateSendingFeed(activity) {
    if (!Array.isArray(activity.entries) || activity.entries.length > 3 ||
        typeof activity.label !== 'string' || activity.entries.some(entry =>
          !Number.isInteger(entry.id) || ['broker', 'message', 'time', 'sent_at'].some(key => typeof entry[key] !== 'string'))) {
      throw new Error('Invalid sending feed');
    }
    const feed = document.getElementById('sending-feed');
    const existing = new Map([...feed.children].map(row => [Number(row.dataset.eventId), row]));
    const rows = activity.entries.map(entry => {
      let row = existing.get(entry.id);
      if (!row) {
        row = document.createElement('li');
        row.dataset.eventId = String(entry.id);
        row.className = 'new-send';
        const copy = document.createElement('span');
        const message = document.createElement('span');
        message.className = 'send-event-message';
        copy.append(document.createElement('strong'), message);
        row.append(document.createElement('time'), copy);
      }
      const time = row.querySelector('time');
      time.textContent = entry.time;
      time.dateTime = entry.sent_at;
      time.title = entry.sent_at;
      row.querySelector('strong').textContent = entry.broker;
      row.querySelector('.send-event-message').textContent = entry.message;
      return row;
    });
    // Leave unchanged rows in place: no repeated animation, focus changes or page reload.
    if (rows.length !== feed.children.length || rows.some((row, index) => feed.children[index] !== row)) {
      existing.forEach(row => row.classList.remove('new-send'));
      feed.replaceChildren(...rows);
    }
    document.getElementById('sending-empty').hidden = rows.length > 0;
    document.getElementById('sending-feed-label').textContent = activity.label;
  }

  async function refresh() {
    if (document.hidden || fetching || pauseDialog?.open) return;
    fetching = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch("/api/status", {
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
      });
      if (!response.ok) throw new Error("Status unavailable");
      const data = await response.json();
      if (!data.automation || typeof data.automation.title !== 'string') throw new Error('Invalid status');
      if (!data.sending_activity || typeof data.sending_activity.last_sent !== 'string' ||
          typeof data.sending_activity.next_step !== 'string') throw new Error('Invalid sending status');
      updateSendingFeed(data.sending_activity);
      document.getElementById('sending-next').textContent = data.sending_activity.next_step;
      document.getElementById('sending-next').hidden = !data.sending_activity.next_step;
      const attention = document.getElementById('attention-shortcut');
      if (attention && Number.isInteger(data.attention_count)) {
        const count = data.attention_count;
        attention.dataset.needed = String(count > 0);
        attention.textContent = count ? `${count} ${count === 1 ? 'request needs' : 'requests need'} you →` : 'Nothing needs you';
      }
      const sentCount = document.getElementById('sent-request-count');
      const doneCount = document.getElementById('completed-request-count');
      if (sentCount && Number.isInteger(data.sent_requests)) sentCount.textContent = data.sent_requests;
      if (doneCount && data.counts) doneCount.textContent =
        (data.counts.removed || 0) + (data.counts.done || 0) + (data.counts.not_found || 0);
      const chart = data.progress_chart;
      const plot = document.getElementById('progress-plot');
      if (plot && chart && Number.isInteger(chart.maximum)) {
        plot.hidden = chart.maximum === 0;
        document.getElementById('progress-empty').hidden = chart.maximum !== 0;
        plot.querySelector('.sent-line').setAttribute('d', chart.sent_path);
        plot.querySelector('.completion-line').setAttribute('d', chart.path);
        document.getElementById('progress-maximum').textContent = chart.maximum;
        document.getElementById('progress-start').textContent = chart.start;
        document.getElementById('progress-end').textContent = chart.end;
        document.getElementById('completion-graph-desc').textContent = chart.description;
        const missing = document.getElementById('progress-undated');
        missing.hidden = !chart.missing_note;
        missing.textContent = chart.missing_note;
      }
      if (data.automation) {
        const state = data.automation;
        document.querySelector('.campaign-card').dataset.state = state.state;
        document.getElementById('automation-title').textContent = state.title;
        document.getElementById('automation-instruction').textContent = state.instruction;
        document.getElementById('automation-instruction').hidden = state.state !== 'blocked';
        if (gmailConnection && gmailLabel) {
          const connected = state.mailbox === 'Connected';
          gmailConnection.dataset.connected = String(connected);
          gmailConnection.href = connected ? '/campaign#mailbox-heading' : '/gmail/connect';
          gmailLabel.textContent = connected ? 'Gmail connected' : 'Reconnect Gmail';
        }
        document.querySelectorAll('[data-control]').forEach(el => { el.hidden = el.dataset.control !== state.control; });
        document.querySelector('[data-control="plan"]').textContent = state.state === 'stopped' ? 'Start automatic emails' : 'Open settings';
      }
      warning.hidden = true;
    } catch {
      status.textContent = "Status unavailable";
      document.getElementById('sending-next').textContent = 'Live sending status is unavailable.';
      document.getElementById('sending-next').hidden = false;
      document.getElementById('automation-title').textContent = "Status unavailable";
      document.querySelector('.campaign-card').dataset.state = "blocked";
      if (gmailConnection && gmailLabel) {
        gmailConnection.dataset.connected = 'unknown';
        gmailConnection.href = '/campaign#mailbox-heading';
        gmailLabel.textContent = 'Gmail status unavailable';
      }
      warning.hidden = false;
    } finally {
      clearTimeout(timeout);
      fetching = false;
    }
  }

  setInterval(refresh, 30000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
  window.addEventListener("pageshow", event => {
    if (event.persisted) refresh();
  });
})();
