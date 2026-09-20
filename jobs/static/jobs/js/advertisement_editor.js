(function () {
    function wrapSelection(style) {
        var selection = window.getSelection();
        if (!selection.rangeCount || selection.isCollapsed) {
            return;
        }
        var range = selection.getRangeAt(0);
        var span = document.createElement('span');
        Object.keys(style).forEach(function (property) {
            span.style[property] = style[property];
        });
        try {
            range.surroundContents(span);
        } catch (error) {
            span.appendChild(range.extractContents());
            range.insertNode(span);
        }
        selection.removeAllRanges();
        selection.addRange(range);
    }

    function wrapSavedRange(editor, savedRange, style) {
        if (!savedRange || savedRange.collapsed || !editor.contains(savedRange.commonAncestorContainer)) {
            return savedRange;
        }
        var range = savedRange.cloneRange();
        var span = document.createElement('span');
        Object.keys(style).forEach(function (property) {
            span.style[property] = style[property];
        });
        span.appendChild(range.extractContents());
        range.insertNode(span);
        var selection = window.getSelection();
        selection.removeAllRanges();
        var appliedRange = document.createRange();
        appliedRange.selectNodeContents(span);
        selection.addRange(appliedRange);
        return appliedRange.cloneRange();
    }

    function linkSavedRange(editor, savedRange, url) {
        if (!savedRange || savedRange.collapsed || !editor.contains(savedRange.commonAncestorContainer)) {
            return savedRange;
        }
        var range = savedRange.cloneRange();
        var link = document.createElement('a');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.appendChild(range.extractContents());
        range.insertNode(link);
        var selection = window.getSelection();
        selection.removeAllRanges();
        var appliedRange = document.createRange();
        appliedRange.selectNodeContents(link);
        selection.addRange(appliedRange);
        return appliedRange.cloneRange();
    }

    function sync(editor) {
        var textarea = editor.parentElement.querySelector('textarea');
        textarea.value = editor.innerHTML;
    }

    function restoreSelection(editor, savedRange) {
        if (!savedRange) {
            return;
        }
        editor.focus();
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(savedRange);
    }

    function saveSelection(editor) {
        var selection = window.getSelection();
        if (selection.rangeCount && !selection.isCollapsed && editor.contains(selection.anchorNode)) {
            return selection.getRangeAt(0).cloneRange();
        }
        return null;
    }

    function applySize(editor, savedRange, input) {
        var size = parseInt(input.value, 10);
        if (!size || size < 1 || size > 2000) {
            return savedRange;
        }
        savedRange = saveSelection(editor) || savedRange;
        return wrapSavedRange(editor, savedRange, {fontSize: size + 'px'});
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.advertisement-editor').forEach(function (container) {
            var editor = container.querySelector('.advertisement-editor-content');
            var textarea = container.querySelector('textarea');
            var savedRange = null;

            editor.addEventListener('mouseup', function () {
                var selection = window.getSelection();
                if (selection.rangeCount && !selection.isCollapsed && editor.contains(selection.anchorNode)) {
                    savedRange = selection.getRangeAt(0).cloneRange();
                }
            });
            editor.addEventListener('keyup', function () {
                savedRange = saveSelection(editor) || savedRange;
            });
            document.addEventListener('selectionchange', function () {
                savedRange = saveSelection(editor) || savedRange;
            });

            container.querySelectorAll('[data-ad-command]').forEach(function (control) {
                control.addEventListener('mousedown', function (event) {
                    savedRange = saveSelection(editor) || savedRange;
                    if (control.tagName === 'BUTTON') {
                        event.preventDefault();
                    }
                });
                control.addEventListener('click', function () {
                    var command = control.dataset.adCommand;
                    if (command === 'apply') {
                        var sizeInput = container.querySelector('[data-ad-command="size"]');
                        if (sizeInput && savedRange) {
                            savedRange = applySize(editor, savedRange, sizeInput);
                        }
                        sync(editor);
                        control.textContent = 'Applied';
                        window.setTimeout(function () {
                            control.textContent = 'Apply';
                        }, 1200);
                        return;
                    }
                    if (command === 'size-apply') {
                        var sizeInput = container.querySelector('[data-ad-command="size"]');
                        savedRange = applySize(editor, savedRange, sizeInput);
                        sync(editor);
                        return;
                    }
                    if (command === 'color' || command === 'background' || command === 'size') {
                        return;
                    }
                    restoreSelection(editor, savedRange);
                    if (command === 'formatBlock') {
                        document.execCommand(command, false, control.value);
                    } else if (command === 'justify') {
                        document.execCommand('justify' + control.value.charAt(0).toUpperCase() + control.value.slice(1), false, null);
                    } else if (command === 'bold' || command === 'italic' || command === 'underline' || command === 'strikeThrough' || command === 'insertUnorderedList' || command === 'insertOrderedList' || command === 'removeFormat') {
                        document.execCommand(command, false, null);
                    } else if (command === 'insertImage') {
                        var imageUrl = window.prompt('Paste image URL', 'https://');
                        if (!imageUrl || !imageUrl.trim()) {
                            return;
                        }
                        var img = document.createElement('img');
                        img.src = imageUrl.trim();
                        img.alt = 'Inserted image';
                        img.style.maxWidth = '100%';
                        img.style.height = 'auto';
                        img.style.borderRadius = '12px';
                        img.style.display = 'block';
                        img.style.margin = '1rem 0';
                        document.execCommand('insertHTML', false, img.outerHTML);
                    } else if (command === 'color') {
                        wrapSelection({color: control.value});
                    } else if (command === 'background') {
                        wrapSelection({backgroundColor: control.value});
                    } else if (command === 'link') {
                        var linkInput = container.querySelector('[data-ad-link-url]');
                        var url = linkInput.value.trim();
                        if (/^(https?:\/\/|mailto:)/i.test(url)) {
                            savedRange = linkSavedRange(editor, savedRange, url);
                            linkInput.value = '';
                        }
                    }
                    sync(editor);
                    savedRange = saveSelection(editor) || savedRange;
                });
                control.addEventListener('input', function () {
                    var command = control.dataset.adCommand;
                    if (command !== 'size') {
                        return;
                    }
                    restoreSelection(editor, savedRange);
                    savedRange = applySize(editor, savedRange, control);
                    savedRange = saveSelection(editor) || savedRange;
                    sync(editor);
                });
            });
            editor.addEventListener('input', function () {
                sync(editor);
            });
            container.querySelectorAll('[data-ad-command="color"], [data-ad-command="background"]').forEach(function (control) {
                control.addEventListener('change', function () {
                    restoreSelection(editor, savedRange);
                    if (control.dataset.adCommand === 'color') {
                        savedRange = wrapSavedRange(editor, savedRange, {color: control.value});
                    } else {
                        savedRange = wrapSavedRange(editor, savedRange, {backgroundColor: control.value});
                    }
                    sync(editor);
                    savedRange = saveSelection(editor) || savedRange;
                });
            });
            textarea.form.addEventListener('submit', function () {
                sync(editor);
            });
        });
    });
}());
