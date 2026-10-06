// Progressive enhancement only: ordinary server forms work without JavaScript.
const addEmail = document.querySelector('#add-email');
addEmail?.addEventListener('click', event => {
  event.preventDefault();
  const group = document.querySelector('#matching-emails');
  const index = group.querySelectorAll('input').length + 1;
  if (index > 20) return;
  const entry = document.createElement('div');
  entry.className = 'email-entry';
  const label = document.createElement('label');
  label.className = 'sr-only';
  label.htmlFor = `matching-${index}`;
  label.textContent = `Email address ${index}`;
  const input = document.createElement('input');
  Object.assign(input, {type: 'email', id: label.htmlFor, name: 'emails', autocomplete: 'email', maxLength: 254});
  input.setAttribute('aria-describedby', 'emails-help');
  entry.append(label, input);
  group.append(entry);
  input.focus();
});
document.querySelector('[aria-invalid="true"]')?.focus();
