// This gallery stores only a visual preference, never changes app settings or requests.
(() => {
  const names = { conservatory: 'Conservatory', porcelain: 'Porcelain', atelier: 'Atelier', midnight: 'Midnight' };
  const key = 'erasure-design-preview-choice';
  const sample = document.querySelector('.design-sample');
  const label = document.getElementById('design-selection');
  const saved = document.getElementById('design-saved');
  let current = 'conservatory';
  function show(design) {
    if (!Object.hasOwn(names, design)) return;
    current = design;
    sample.dataset.theme = design;
    label.textContent = `Previewing ${names[design]}`;
    document.querySelectorAll('[data-design]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.design === design));
    });
  }
  try {
    const choice = localStorage.getItem(key);
    if (Object.hasOwn(names, choice)) {
      show(choice);
      saved.textContent = `Your saved choice: ${names[choice]}. The live app is unchanged.`;
    } else if (choice) {
      saved.textContent = 'Your previous direction was retired. Previewing Conservatory; the live app is unchanged.';
    }
  } catch { /* Preview still works if browser storage is unavailable. */ }
  document.querySelectorAll('[data-design]').forEach(button => {
    button.addEventListener('click', () => show(button.dataset.design));
  });
  document.getElementById('choose-design').addEventListener('click', () => {
    try {
      localStorage.setItem(key, current);
      saved.textContent = `Chosen: ${names[current]}. Apply it in Settings → Appearance.`;
    } catch {
      saved.textContent = `Previewing ${names[current]}. Apply it in Settings → Appearance.`;
    }
  });
})();
