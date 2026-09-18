document.addEventListener("DOMContentLoaded", function () {
    var activeModal = null;
    var modalTrigger = null;
    var languageKey = "memovault-language";
    var sourcePath = document.body.getAttribute("data-form-return-to");
    if (sourcePath) {
        window.history.replaceState(null, "", sourcePath);
    }
    document.querySelectorAll('input[name="return_to"]').forEach(function (input) {
        input.value = window.location.pathname + window.location.search;
    });

    var activeTypeMenu = null;
    function closeTypeMenu() {
        if (!activeTypeMenu) return;
        activeTypeMenu.querySelector(".sidebar-type-menu").hidden = true;
        activeTypeMenu.querySelector(".sidebar-type-more").setAttribute("aria-expanded", "false");
        activeTypeMenu = null;
    }
    document.querySelectorAll(".sidebar-type-more").forEach(function (button) {
        button.addEventListener("click", function () {
            var actions = button.closest(".sidebar-type-actions");
            var wasOpen = activeTypeMenu === actions;
            closeTypeMenu();
            if (wasOpen) return;
            activeTypeMenu = actions;
            var menu = actions.querySelector(".sidebar-type-menu");
            menu.hidden = false;
            button.setAttribute("aria-expanded", "true");
            var rect = button.getBoundingClientRect();
            menu.style.left = Math.max(8, Math.min(rect.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8)) + "px";
            menu.style.top = Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - menu.offsetHeight - 8)) + "px";
        });
    });
    document.addEventListener("click", function (event) {
        if (activeTypeMenu && !activeTypeMenu.contains(event.target)) closeTypeMenu();
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") closeTypeMenu();
    });
    window.addEventListener("resize", closeTypeMenu);

    var activeAccount = null;
    function closeAccount(restoreFocus) {
        if (!activeAccount) return;
        var trigger = activeAccount.querySelector('.account-trigger');
        activeAccount.querySelector('.account-menu').hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        activeAccount = null;
        if (restoreFocus) trigger.focus();
    }
    function openAccount(account) {
        closeAccount(false);
        closeTypeMenu();
        activeAccount = account;
        account.querySelector('.account-menu').hidden = false;
        account.querySelector('.account-trigger').setAttribute('aria-expanded', 'true');
        account.querySelector('[role="menuitem"]').focus();
    }
    document.querySelectorAll('.account-area').forEach(function (account) {
        var trigger = account.querySelector('.account-trigger');
        var menu = account.querySelector('.account-menu');
        var item = menu.querySelector('[role="menuitem"]');
        trigger.addEventListener('click', function () {
            if (activeAccount === account) closeAccount(false);
            else openAccount(account);
        });
        trigger.addEventListener('keydown', function (event) {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                openAccount(account);
            }
        });
        menu.addEventListener('keydown', function (event) {
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                item.focus();
            }
            if (event.key === 'Tab') {
                // Resume natural tab order from the trigger after closing the menu.
                closeAccount(true);
            }
        });
    });
    document.addEventListener('click', function (event) {
        if (activeAccount && !activeAccount.contains(event.target)) closeAccount(false);
    });
    document.addEventListener('focusin', function (event) {
        if (activeAccount && !activeAccount.contains(event.target)) closeAccount(false);
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && activeAccount) {
            event.preventDefault();
            closeAccount(true);
        }
    });
    window.addEventListener('resize', function () { closeAccount(false); });

    function getSavedLanguage() {
        var savedLanguage = localStorage.getItem(languageKey);

        if (savedLanguage === "zh") {
            return "zh";
        }

        return "en";
    }

    function updateLanguageButtons(language) {
        document.querySelectorAll("[data-language]").forEach(function (button) {
            if (button.getAttribute("data-language") === language) {
                button.classList.add("is-active");
            } else {
                button.classList.remove("is-active");
            }
        });
    }

    function applyLanguage(language) {
        document.documentElement.lang = language === "zh" ? "zh-CN" : "en";

        document.querySelectorAll("[data-en][data-zh]").forEach(function (element) {
            element.textContent = element.getAttribute("data-" + language);
        });

        document.querySelectorAll("[data-placeholder-en][data-placeholder-zh]").forEach(function (element) {
            element.setAttribute(
                "placeholder",
                element.getAttribute("data-placeholder-" + language)
            );
        });

        document.querySelectorAll("[data-aria-label-en][data-aria-label-zh]").forEach(function (element) {
            element.setAttribute(
                "aria-label",
                element.getAttribute("data-aria-label-" + language)
            );
        });

        updateLanguageButtons(language);
    }

    function getFocusableElement(modal) {
        return modal.querySelector("[data-modal-initial-focus]") ||
            modal.querySelector("input:not([type=hidden]), textarea, select") ||
            modal.querySelector("button, a[href]");
    }

    function openModal(modalId, trigger) {
        var modal = document.getElementById(modalId);

        if (!modal) {
            return;
        }

        activeModal = modal;
        modalTrigger = trigger || null;
        closeAccount(false);
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");

        var firstField = getFocusableElement(modal);

        if (firstField) {
            firstField.focus();
        }
    }

    function closeModal(modal) {
        if (!modal) {
            return;
        }

        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");

        if (activeModal === modal) {
            activeModal = null;
            var trigger = modalTrigger;
            modalTrigger = null;
            // Restore after the dismissing click has finished bubbling, so the
            // account outside-click handler does not immediately hide it again.
            queueMicrotask(function () {
                if (!trigger || !trigger.isConnected || activeModal) return;
                var account = trigger.closest('.account-area');
                if (account) {
                    // A resize may have switched between sidebar and mobile UI.
                    if (!account.getClientRects().length) {
                        account = Array.from(document.querySelectorAll('.account-area')).find(function (area) {
                            return area.getClientRects().length;
                        });
                    }
                    if (account) openAccount(account);
                } else if (trigger.getClientRects().length) {
                    trigger.focus();
                }
            });
        }
    }

    document.querySelectorAll("[data-modal-open]").forEach(function (button) {
        button.addEventListener("click", function () {
            if (button.hasAttribute("data-rename-type-id")) {
                var typeName = button.getAttribute("data-rename-type-name");
                var renameInput = document.getElementById("rename-type-name");
                renameInput.value = typeName;
                renameInput.removeAttribute("aria-invalid");
                document.getElementById("rename-current-name").textContent = typeName;
                document.getElementById("rename-type-form").action =
                    "/types/" + button.getAttribute("data-rename-type-id") + "/rename";
                document.getElementById("rename-type-error").hidden = true;
            }
            closeTypeMenu();
            openModal(button.getAttribute("data-modal-open"), button);
            if (button.hasAttribute("data-delete-type-id")) {
                document.getElementById("delete-current-name").textContent =
                    button.getAttribute("data-delete-type-name");
                document.getElementById("delete-type-form").action =
                    "/types/" + button.getAttribute("data-delete-type-id") + "/delete";
                document.getElementById("delete-type-error").hidden = true;
            }
        });
    });

    document.querySelectorAll("[data-modal-close]").forEach(function (button) {
        button.addEventListener("click", function () {
            closeModal(button.closest(".modal-backdrop"));
        });
    });

    document.querySelectorAll(".modal-backdrop").forEach(function (modal) {
        modal.addEventListener("click", function (event) {
            if (event.target === modal) {
                closeModal(modal);
            }
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && activeModal) {
            event.preventDefault();
            closeModal(activeModal);
        }
        if (event.key === "Tab" && activeModal) {
            var controls = Array.from(activeModal.querySelectorAll(
                'button:not(:disabled), a[href], input:not([type="hidden"]):not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]'
            )).filter(function (element) { return element.getClientRects().length; });
            var first = controls[0];
            var last = controls[controls.length - 1];
            if (first && (event.shiftKey && document.activeElement === first ||
                          !event.shiftKey && document.activeElement === last ||
                          !activeModal.contains(document.activeElement))) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            }
        }
    });

    document.querySelectorAll("[data-language]").forEach(function (button) {
        button.addEventListener("click", function () {
            var language = button.getAttribute("data-language");

            localStorage.setItem(languageKey, language);
            applyLanguage(language);
        });
    });

    var sidebarCollapsedKey = "memovault-sidebar-collapsed";
    var collapsedTypes = new Set();

    try {
        var savedCollapsedTypes = JSON.parse(localStorage.getItem(sidebarCollapsedKey));
        if (Array.isArray(savedCollapsedTypes)) {
            savedCollapsedTypes.forEach(function (key) {
                if (typeof key === "string" && /^(type-[0-9]+|ungrouped)$/.test(key)) {
                    collapsedTypes.add(key);
                }
            });
        }
    } catch (error) {
        // Invalid JSON or unavailable storage defaults to all types expanded.
    }

    document.querySelectorAll(".sidebar-type-toggle").forEach(function (button) {
        var row = button.closest(".sidebar-type-row");
        var recordList = row ? row.nextElementSibling : null;
        var typeKey = button.getAttribute("data-type-key");

        if (!recordList || !recordList.classList.contains("sidebar-record-list")) {
            return;
        }

        function applyCollapsedState(isCollapsed) {
            recordList.hidden = isCollapsed;
            button.setAttribute("aria-expanded", String(!isCollapsed));
            button.textContent = isCollapsed ? "▸" : "▾";
        }

        applyCollapsedState(collapsedTypes.has(typeKey));

        button.addEventListener("click", function () {
            applyCollapsedState(!recordList.hidden);

            if (recordList.hidden) {
                collapsedTypes.add(typeKey);
            } else {
                collapsedTypes.delete(typeKey);
            }

            try {
                localStorage.setItem(sidebarCollapsedKey, JSON.stringify(Array.from(collapsedTypes)));
            } catch (error) {
                // Keep toggling usable when storage is unavailable or full.
            }
        });
    });

    applyLanguage(getSavedLanguage());

    var typeSearch = document.getElementById("sidebar-type-search");
    var hideEmpty = document.getElementById("sidebar-hide-empty");
    var hideEmptyKey = "memovault-hide-empty-types";
    if (typeSearch && hideEmpty) {
        try { hideEmpty.checked = localStorage.getItem(hideEmptyKey) === "true"; }
        catch (error) { hideEmpty.checked = false; }
        function normalizeTypeName(value) {
            return value.normalize("NFKC").toLowerCase();
        }
        function filterSidebarTypes() {
            closeTypeMenu();
            var query = normalizeTypeName(typeSearch.value.trim());
            document.querySelectorAll(".sidebar-type-row").forEach(function (row) {
                var ungrouped = row.classList.contains("sidebar-type-ungrouped");
                // Match both built-in translations regardless of the UI language.
                var name = ungrouped ? "Ungrouped 未分组" : row.getAttribute("data-type-name") || "";
                var filtered = !normalizeTypeName(name).includes(query) ||
                    (hideEmpty.checked && !ungrouped && row.getAttribute("data-record-count") === "0");
                row.classList.toggle("is-type-filtered", filtered);
                var list = row.nextElementSibling;
                if (list && list.classList.contains("sidebar-record-list")) {
                    // Keep the collapse-owned hidden attribute untouched.
                    list.classList.toggle("is-type-filtered", filtered);
                }
            });
        }
        typeSearch.addEventListener("input", filterSidebarTypes);
        hideEmpty.addEventListener("change", function () {
            try { localStorage.setItem(hideEmptyKey, String(hideEmpty.checked)); }
            catch (error) {}
            filterSidebarTypes();
        });
        filterSidebarTypes();
    }

    var sidebarScroll = document.querySelector(".sidebar-main");
    if (sidebarScroll) {
        var sidebarScrollKey = "memovault-sidebar-scroll";
        var savedScroll = 0;
        try {
            var rawScroll = localStorage.getItem(sidebarScrollKey);
            if (rawScroll !== null && /^\d+(?:\.\d+)?$/.test(rawScroll)) {
                var parsedScroll = Number(rawScroll);
                if (Number.isFinite(parsedScroll)) savedScroll = parsedScroll;
            }
        } catch (error) {}
        // Restore after the saved collapse state and language have been applied.
        sidebarScroll.scrollTop = savedScroll;
        sidebarScroll.addEventListener("scroll", function () {
            closeTypeMenu();
            try { localStorage.setItem(sidebarScrollKey, String(sidebarScroll.scrollTop)); }
            catch (error) {}
        }, { passive: true });
    }

    var autoOpenModal = document.querySelector("[data-modal-auto-open]");
    if (autoOpenModal) {
        openModal(autoOpenModal.id);
    }

    if (window.location.hash === "#add-record") {
        openModal("add-record-modal");
    }
});
