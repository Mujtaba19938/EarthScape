// Dashboard interface behaviour: menus, sidebar, dialogs, auto-submit, toasts and refresh.

// Icons
if (window.lucide) lucide.createIcons();

// Header menus
const panels = [...document.querySelectorAll('[data-menu-panel]')];

function closeMenus(except) {
  panels.forEach((panel) => { if (panel !== except) panel.classList.add('hidden'); });
  document.querySelectorAll('[data-menu]').forEach((button) => {
    if (!except || button.dataset.menu !== except.id) button.setAttribute('aria-expanded', 'false');
  });
}

document.querySelectorAll('[data-menu]').forEach((button) => {
  button.addEventListener('click', () => {
    const panel = document.getElementById(button.dataset.menu);
    closeMenus(panel);
    const open = panel.classList.toggle('hidden') === false;
    button.setAttribute('aria-expanded', String(open));
  });
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('[data-menu], [data-menu-panel]')) closeMenus();
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenus(); });

// Sidebar collapse
const sidebar = document.getElementById('sidebar');

function setSidebar(open) {
  sidebar.classList.toggle('w-64', open);
  sidebar.classList.toggle('w-16', !open);
  document.querySelectorAll('.sidebar-label, .sidebar-heading').forEach((element) => element.classList.toggle('hidden', !open));
  document.getElementById('sidebar-footer').classList.toggle('hidden', !open);
  try { localStorage.setItem('es_sidebar', open ? 'open' : 'closed'); } catch (error) { /* private window */ }
}

if (sidebar) {
  let saved = null;
  try { saved = localStorage.getItem('es_sidebar'); } catch (error) { /* private window */ }
  if (saved === 'closed' || (saved === null && window.innerWidth < 768)) setSidebar(false);
  document.getElementById('btn-toggle-sidebar').addEventListener('click', () => setSidebar(sidebar.classList.contains('w-16')));
}

// Dialogs
document.querySelectorAll('[data-open]').forEach((button) => {
  button.addEventListener('click', () => document.getElementById(button.dataset.open).showModal());
});
document.querySelectorAll('dialog [data-close]').forEach((button) => {
  button.addEventListener('click', () => button.closest('dialog').close());
});

// Auto-submit selects
document.querySelectorAll('[data-autosubmit]').forEach((select) => {
  select.addEventListener('change', () => select.form.requestSubmit());
});

// Confirm and busy buttons
document.querySelectorAll('form').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    const button = event.submitter;
    if (button && button.dataset.busy) {
      button.textContent = button.dataset.busy;
      setTimeout(() => { button.disabled = true; }, 0);
    }
  });
});

// Toasts fade
document.querySelectorAll('[data-toast]').forEach((toast) => setTimeout(() => toast.remove(), 5000));

// Auto refresh
const refresh = Number(document.body.dataset.refresh || 0);
if (refresh > 0) {
  setTimeout(() => {
    // Not while someone is typing
    const typing = document.activeElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    if (!typing && !document.querySelector('dialog[open]')) location.reload();
  }, refresh * 1000);
}
