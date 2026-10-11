document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-load-more]');
    if (!button || button.dataset.loading === 'true') {
        return;
    }

    event.preventDefault();
    var target = document.getElementById(button.dataset.itemsTarget);
    if (!target) {
        window.location.assign(button.href);
        return;
    }

    var nextUrl = button.href;
    button.dataset.loading = 'true';
    button.setAttribute('aria-busy', 'true');
    target.setAttribute('aria-busy', 'true');

    fetch(nextUrl, {
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (response) {
        if (!response.ok) {
            throw new Error('Unable to load the next page.');
        }
        return response.text();
    }).then(function (html) {
        var nextDocument = new DOMParser().parseFromString(html, 'text/html');
        var nextTarget = nextDocument.getElementById(button.dataset.itemsTarget);
        if (!nextTarget) {
            throw new Error('The next page did not include its items.');
        }
        Array.from(nextTarget.children).forEach(function (item) {
            target.appendChild(document.importNode(item, true));
        });

        var nextButton = nextDocument.querySelector('[data-load-more]');
        if (!nextButton) {
            button.remove();
            return;
        }
        button.href = nextButton.href;
    }).catch(function () {
        window.location.assign(nextUrl);
    }).finally(function () {
        target.removeAttribute('aria-busy');
        if (button.isConnected) {
            button.removeAttribute('aria-busy');
            button.dataset.loading = 'false';
        }
    });
});
