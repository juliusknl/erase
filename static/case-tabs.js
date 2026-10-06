// Preserve older inbox/action links that predate the tabbed request page.
const hash = window.location.hash;
const action = hash.match(/^#action-(\d+)$/);
if (action && !document.getElementById(`action-${action[1]}`)) {
  const url = new URL(window.location.href);
  if (url.searchParams.get('step') !== action[1]) {
    url.searchParams.set('tab', 'overview');
    url.searchParams.set('step', action[1]);
    window.location.replace(url);
  }
}
if (hash === '#reply-composer' && !document.querySelector(hash)) {
  const url = new URL(window.location.href);
  const target = url.searchParams.get('tab') === 'conversation' ? 'overview' : 'conversation';
  url.searchParams.set('tab', target);
  // Only one fallback navigation. A request without a sent email has no composer.
  if (!url.searchParams.has('composer')) {
    url.searchParams.set('composer', '1');
    window.location.replace(url);
  }
}
