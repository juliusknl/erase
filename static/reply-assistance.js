(() => {
  const dialog = document.getElementById('reply-assistance-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  if (dialog.open) { dialog.close(); dialog.showModal(); }
  document.querySelectorAll('[data-assistance-open]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    dialog.showModal();
    document.getElementById('reply-assistance-title').focus();
  }));
  dialog.querySelectorAll('[data-assistance-close]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    dialog.close();
  }));
  dialog.addEventListener('close', () => {
    // Converting an initially open dialog to a modal queues a close event.
    if (dialog.open) return;
    const key = dialog.querySelector('[name=api_key]');
    if (key) key.value = '';
    const url = new URL(location.href);
    ['reply_assistance', 'assistance_saved', 'assistance_error', 'assistance_provider', 'chatgpt_disconnected', 'chatgpt_first'].forEach(name => url.searchParams.delete(name));
    history.replaceState(null, '', url);
  });
  dialog.querySelector('[data-assistance-connect]')?.addEventListener('submit', event => {
    event.currentTarget.querySelector('button').disabled = true;
    event.currentTarget.querySelector('button').textContent = 'Connecting…';
  });
  const tabs = [...dialog.querySelectorAll('[data-assistance-provider]')];
  const selectProvider = tab => {
    tabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !active;
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectProvider(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + 1) % tabs.length];
      selectProvider(next); next.focus();
    });
  });
  selectProvider(tabs.find(tab => tab.getAttribute('aria-selected') === 'true') || tabs[0]);
  dialog.querySelector('[data-chatgpt-connect]')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button');
    const status = form.querySelector('[data-chatgpt-status]');
    button.disabled = true;
    status.hidden = false;
    status.textContent = 'Opening ChatGPT…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not connect. Reload the page and try again.');
      const url = new URL(result.url, location.origin);
      if (url.origin !== location.origin && url.origin !== 'https://auth.openai.com') throw new Error('Unexpected sign-in address.');
      location.assign(url.href);
    } catch (error) {
      status.textContent = error.message || 'Could not connect. Try again.';
      button.disabled = false;
    }
  });
})();
