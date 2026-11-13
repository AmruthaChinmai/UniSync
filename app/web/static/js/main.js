/**
 * main.js - Client-side interactions for UniSync
 */

document.addEventListener('DOMContentLoaded', () => {
    // Auto-dismiss flash alerts after 6 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.4s ease';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 400);
        }, 6000);
    });

    // Keyboard shortcut '/' to focus search bar
    const searchInput = document.querySelector('.search-input');
    if (searchInput) {
        window.addEventListener('keydown', (e) => {
            if (e.key === '/' && document.activeElement !== searchInput) {
                e.preventDefault();
                searchInput.focus();
            }
        });
    }
});
