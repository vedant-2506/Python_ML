// main.js – shared utilities for the HireRank AI frontend prototype
// This file provides a simple toast helper and generic UI initializers.

/**
 * Show a Bootstrap toast notification.
 * @param {string} message - Text to display.
 * @param {string} type - One of 'success', 'info', 'warning', 'danger'.
 */
function showToast(message, type = 'info') {
  // Ensure a container exists
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'position-fixed top-0 end-0 p-3';
    container.style.zIndex = 1055;
    document.body.appendChild(container);
  }

  const toastEl = document.createElement('div');
  toastEl.className = `toast align-items-center text-white bg-${type} border-0`;
  toastEl.role = 'alert';
  toastEl.setAttribute('aria-live', 'assertive');
  toastEl.setAttribute('aria-atomic', 'true');

  const toastBody = document.createElement('div');
  toastBody.className = 'd-flex';
  toastBody.innerHTML = `
    <div class="toast-body">${message}</div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
  `;
  toastEl.appendChild(toastBody);
  container.appendChild(toastEl);

  const toast = new bootstrap.Toast(toastEl, { delay: 3000 });
  toast.show();
}

// Export to global scope for inline scripts to access.
window.showToast = showToast;

// Optional: initialize Bootstrap tooltips globally.
document.addEventListener('DOMContentLoaded', function () {
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
});

