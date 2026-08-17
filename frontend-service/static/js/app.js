// app.js - small progressive-enhancement helpers, loaded once and cached
// by the browser across every page (unlike inline <script> blocks).

document.addEventListener('DOMContentLoaded', function () {
    // Auto-dismiss success/error alert banners after 5s so they don't
    // linger on the page and clutter the UI during a long session.
    document.querySelectorAll('.alert').forEach(function (alertEl) {
        setTimeout(function () {
            // Reuse Bootstrap's own Alert component if it's loaded,
            // falling back to a plain DOM removal otherwise.
            if (window.bootstrap && window.bootstrap.Alert) {
                const instance = window.bootstrap.Alert.getOrCreateInstance(alertEl);
                instance.close();
            } else {
                alertEl.remove();
            }
        }, 5000);
    });
});
