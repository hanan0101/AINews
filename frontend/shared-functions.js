// Shared functions used by both News.html and versions.html.

function escapeHtml(v=''){return String(v).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}

// Flashes `message` into `element` (expects the shared .toast CSS from
// tokens.css) and auto-hides it after `duration` ms.
function flashToastElement(element, message, duration=2200){
  if(!element) return;
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(element._toastTimer);
  element._toastTimer = setTimeout(()=>element.classList.remove('show'), duration);
}

// Hides every element matching each selector and disables its interaction,
// for admin-only controls in viewer mode. Callers supply their own
// page-specific selector list.
function hideAdminOnlySelectors(selectors){
  selectors.forEach(selector=>{
    document.querySelectorAll(selector).forEach(element=>{
      element.style.display = 'none';
      element.setAttribute('aria-hidden', 'true');
      if('disabled' in element) element.disabled = true;
      element.onclick = null;
    });
  });
}
