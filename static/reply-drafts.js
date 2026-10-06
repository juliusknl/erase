// Keep an incomplete suggested reply in the editor, with a native field error.
const composer = document.querySelector('#reply-composer form');
if (composer) {
  const body = composer.querySelector('textarea[name="body"]');
  const recipient = composer.querySelector('input[name="destination"]');
  const originalBody = body.value;
  const originalRecipient = recipient.value;
  let submitting = false;
  window.addEventListener('beforeunload', (event) => {
    if (!submitting && (body.value !== originalBody || recipient.value !== originalRecipient)) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  body.addEventListener('input', () => body.setCustomValidity(''));
  composer.addEventListener('submit', (event) => {
    if (/\[ADD\b[^\]]*\]/.test(body.value)) {
      event.preventDefault();
      body.setCustomValidity('Fill in or remove every [ADD …] placeholder before sending.');
      body.reportValidity();
    } else {
      submitting = true;
    }
  });
}
