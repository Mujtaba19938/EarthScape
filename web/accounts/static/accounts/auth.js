// Sign-in page behaviour: password toggle and rotating captions.

// Show or hide password
document.querySelectorAll('[data-toggle-password]').forEach((button) => {
  const input = document.getElementById(button.dataset.togglePassword);
  button.addEventListener('click', () => {
    const showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    button.setAttribute('aria-pressed', String(!showing));
    button.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
  });
});

// Rotating captions
const captions = [...document.querySelectorAll('.caption')];
const dots = [...document.querySelectorAll('.dot')];
let current = 0;

function showCaption(index) {
  current = index;
  captions.forEach((caption, i) => caption.classList.toggle('on', i === index));
  dots.forEach((dot, i) => dot.setAttribute('aria-current', String(i === index)));
}

dots.forEach((dot, i) => dot.addEventListener('click', () => showCaption(i)));
if (captions.length && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
  setInterval(() => showCaption((current + 1) % captions.length), 6000);
}

// No double submit
document.querySelectorAll('form').forEach((form) => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
  });
});
