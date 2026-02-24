/**
 * Toast Notification Handler
 * Automatically shows and dismisses Bootstrap toasts from Flask flash messages.
 */

document.addEventListener('DOMContentLoaded', function () {
    const toasts = document.querySelectorAll('.app-toast');

    toasts.forEach(function (toastEl) {
        const toast = new bootstrap.Toast(toastEl, {
            autohide: true,
            delay: 4000
        });
        toast.show();

        // Remove from DOM after hiding so they don't stack up
        toastEl.addEventListener('hidden.bs.toast', function () {
            toastEl.remove();
        });
    });
});
