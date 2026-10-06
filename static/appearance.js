// Onboarding previews immediately; Settings applies the look only after Save.
// Neither preview nor selection persists a preference without form submission.
document.querySelectorAll('.appearance-choices input[name="theme"]').forEach(input => {
  input.addEventListener('change', () => {
    if (!input.checked) return;
    document.querySelector('.appearance-saved')?.setAttribute('hidden', '');
    if (input.closest('.appearance-choices').dataset.preview === 'true') {
      document.documentElement.dataset.theme = input.value;
      document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', input.dataset.scheme);
    }
  });
});
