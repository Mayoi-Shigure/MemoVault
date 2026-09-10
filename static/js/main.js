document.addEventListener("DOMContentLoaded", function () {
    var activeModal = null;

    function getFocusableElement(modal) {
        return modal.querySelector("input, textarea, select") ||
            modal.querySelector("button, a[href]");
    }

    function openModal(modalId) {
        var modal = document.getElementById(modalId);

        if (!modal) {
            return;
        }

        activeModal = modal;
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
        }
    }

    document.querySelectorAll("[data-modal-open]").forEach(function (button) {
        button.addEventListener("click", function () {
            openModal(button.getAttribute("data-modal-open"));
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
            closeModal(activeModal);
        }
    });

    if (window.location.hash === "#add-record") {
        openModal("add-record-modal");
    }
});
