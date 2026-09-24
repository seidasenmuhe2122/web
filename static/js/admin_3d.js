(function () {
    function themeEndpoint() {
        var adminIndex = window.location.pathname.indexOf('/admin/');
        if (adminIndex === -1) {
            return '/admin/theme-config/';
        }
        return window.location.pathname.slice(0, adminIndex + 7) + 'theme-config/';
    }

    function setThemeProperty(name, value) {
        if (value) {
            document.documentElement.style.setProperty(name, value);
        }
    }

    function clearBackgroundMedia() {
        document.querySelectorAll('.admin-3d-background').forEach(function (media) {
            media.pause && media.pause();
            media.remove();
        });
        document.body.classList.remove('admin-custom-background');
        document.documentElement.classList.remove('admin-custom-background');
        delete document.body.dataset.adminBackgroundMode;
        ['.wrapper', '.content-wrapper', '.app-main', '.app-main > .container-fluid'].forEach(function (selector) {
            document.querySelectorAll(selector).forEach(function (element) {
                element.style.removeProperty('background');
            });
        });
    }

    function addBackgroundMedia(config) {
        clearBackgroundMedia();

        if (config.background_mode === 'previous') {
            return;
        }

        var selectedSources = {
            image: {url: config.background_image, video: false},
            video: {url: config.background_video, video: true},
            '3d': {url: config.background_3d, video: true},
            '4k': {url: config.background_4k, video: true},
        };
        var selected = selectedSources[config.background_mode];
        var source = selected && selected.url ? selected : (
            config.background_image ? {url: config.background_image, video: false} :
            config.background_video ? {url: config.background_video, video: true} :
            config.background_3d ? {url: config.background_3d, video: true} :
            config.background_4k ? {url: config.background_4k, video: true} : null
        );
        if (!source) {
            return;
        }

        document.body.classList.add('admin-custom-background');
        document.body.dataset.adminBackgroundMode = config.background_mode || 'image';
        document.documentElement.classList.add('admin-custom-background');

        var media;
        if (source.video) {
            media = document.createElement('video');
            media.autoplay = true;
            media.loop = true;
            media.muted = true;
            media.playsInline = true;
            media.addEventListener('error', function () {
                media.remove();
                if (config.background_image && config.background_mode !== 'image') {
                    addBackgroundMedia({background_mode: 'image', background_image: config.background_image});
                }
            }, {once: true});
            media.addEventListener('canplay', function () {
                media.play().catch(function () {});
            }, {once: true});
        } else {
            media = document.createElement('img');
            media.alt = '';
            media.setAttribute('aria-hidden', 'true');
        }

        media.className = 'admin-3d-background';
        media.src = source.url;
        media.setAttribute('role', 'presentation');
        document.body.prepend(media);

        // Keep the selected media visible even when another admin stylesheet uses !important backgrounds.
        ['.wrapper', '.content-wrapper', '.app-main', '.app-main > .container-fluid'].forEach(function (selector) {
            document.querySelectorAll(selector).forEach(function (element) {
                element.style.setProperty('background', 'transparent', 'important');
            });
        });
    }

    function applyTheme(config) {
        // Apply both variable sets used by the loaded Jazzmin theme and the 3D stylesheet.
        setThemeProperty('--admin-bg', config.workspace_color);
        setThemeProperty('--admin-sidebar', config.sidebar_color);
        setThemeProperty('--admin-cyan', config.accent_color);
        setThemeProperty('--admin-blue', config.primary_color);
        setThemeProperty('--admin-primary', config.primary_color);
        setThemeProperty('--admin-secondary', config.secondary_color);
        setThemeProperty('--admin-purple', config.secondary_color);
        setThemeProperty('--admin-text', config.text_color);
        setThemeProperty('--admin-charcoal', config.sidebar_color);
        setThemeProperty('--admin-pastel-blue', config.accent_color);
        setThemeProperty('--admin-workspace', config.workspace_color);
        addBackgroundMedia(config);
    }

    document.addEventListener('DOMContentLoaded', function () {
        fetch(themeEndpoint(), {credentials: 'same-origin'})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('Unable to load admin theme');
                }
                return response.json();
            })
            .then(applyTheme)
            .catch(function () {
                // CSS defaults remain active if the settings endpoint is unavailable.
            });
    });
}());
