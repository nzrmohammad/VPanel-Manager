document.addEventListener('DOMContentLoaded', function() {
    const sidebar = document.querySelector('.sidebar');

    // ۱. منطق سایدبار دسکتاپ (جمع شدن)
    const sidebarToggle = document.getElementById('sidebar-toggle');
    if (sidebar && sidebarToggle) {
        sidebarToggle.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
            localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
        });
        if (localStorage.getItem('sidebarCollapsed') === 'true') {
            sidebar.classList.add('collapsed');
        }
    }

    // ۲. منطق سایدبار موبایل (منوی کشویی)
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    if (mobileMenuBtn && sidebar) {
        mobileMenuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // *** این خط اصلاح شد ***
            sidebar.classList.toggle('show-on-mobile');
        });

        // بستن منو با کلیک روی لینک‌های داخل آن
        const navLinks = sidebar.querySelectorAll('.sidebar-nav a');
        navLinks.forEach(link => {
            link.addEventListener('click', () => {
                if (sidebar.classList.contains('show-on-mobile')) {
                    sidebar.classList.remove('show-on-mobile');
                }
            });
        });
    }

    // بستن منوی موبایل با کلیک روی محتوای اصلی صفحه
    const mainContent = document.querySelector('.main-content');
    if (mainContent) {
        mainContent.addEventListener('click', () => {
            if (sidebar && sidebar.classList.contains('show-on-mobile')) {
                sidebar.classList.remove('show-on-mobile');
            }
        });
    }

    // ۳. منطق تغییر تم (تاریک/روشن)
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        const themeIcon = themeToggle.querySelector('i');
        const applyTheme = (theme) => {
            if (theme === 'dark') {
                document.body.classList.add('dark-theme');
                if (themeIcon) themeIcon.className = 'ri-sun-line';
            } else {
                document.body.classList.remove('dark-theme');
                if (themeIcon) themeIcon.className = 'ri-moon-line';
            }
        };

        themeToggle.addEventListener('click', () => {
            const isDark = document.body.classList.contains('dark-theme');
            const newTheme = isDark ? 'light' : 'dark';
            localStorage.setItem('theme', newTheme);
            applyTheme(newTheme);
        });

        const savedTheme = localStorage.getItem('theme') || 'light';
        applyTheme(savedTheme);
    }
});