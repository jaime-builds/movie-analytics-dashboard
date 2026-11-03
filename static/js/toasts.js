/**
 * Toast Notification Handler
 * Shows Bootstrap toasts for Flask flash messages, and for messages that page
 * scripts add later through window.showToast (defined in base.html).
 *
 * Errors and warnings stay up longer than confirmations, so there is time to
 * read "Invalid username or password" before it disappears.
 */

(function () {
    'use strict';

    var DELAYS = { danger: 10000, warning: 8000 };
    var DEFAULT_DELAY = 4000;

    function categoryOf(toastEl) {
        var match = toastEl.className.match(/toast-(\w+)/);
        return match ? match[1] : 'info';
    }

    window.initAppToast = function (toastEl) {
        var toast = new bootstrap.Toast(toastEl, {
            autohide: true,
            delay: DELAYS[categoryOf(toastEl)] || DEFAULT_DELAY
        });
        toast.show();

        // Remove from DOM after hiding so they don't stack up
        toastEl.addEventListener('hidden.bs.toast', function () {
            toastEl.remove();
        });
    };

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.app-toast').forEach(window.initAppToast);
    });
})();
