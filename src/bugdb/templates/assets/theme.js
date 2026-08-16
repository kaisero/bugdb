/* BugDB theme control.
 *
 * Loaded as a render-blocking classic script in <head> so `data-theme` is on
 * <html> before first paint — without that, dark-mode users get a white
 * flash. It cannot be inlined: the page's CSP is `script-src 'self'`.
 *
 * localStorage key `bugdb-theme`:
 *   absent  -> follow the OS, live
 *   'light' -> forced light
 *   'dark'  -> forced dark
 */
(function () {
    'use strict';

    var KEY = 'bugdb-theme';
    var mq = window.matchMedia('(prefers-color-scheme: dark)');

    function stored() {
        try {
            return localStorage.getItem(KEY);
        } catch (e) {
            return null; // private mode / storage disabled
        }
    }

    function resolved() {
        var s = stored();
        return s === 'dark' || s === 'light' ? s : mq.matches ? 'dark' : 'light';
    }

    function apply() {
        var theme = resolved();
        document.documentElement.setAttribute('data-theme', theme);
        var btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.setAttribute('aria-checked', String(theme === 'dark'));
        }
    }

    // Only follow the OS while the user has not made an explicit choice.
    mq.addEventListener('change', function () {
        if (!stored()) {
            apply();
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.addEventListener('click', function () {
                try {
                    localStorage.setItem(KEY, resolved() === 'dark' ? 'light' : 'dark');
                } catch (e) {
                    /* storage unavailable: the class still flips for this page */
                }
                apply();
            });
        }
        apply();
    });

    apply(); // before paint
})();
