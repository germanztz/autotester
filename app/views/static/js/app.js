(function () {
    "use strict";

    const THEME_KEY = "autotester.theme";
    const VALID_THEMES = ["light", "dark", "system"];

    function applyTheme(theme) {
        const effective = theme === "system"
            ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
            : theme;
        document.documentElement.setAttribute("data-bs-theme", effective);
    }

    function persistTheme(theme) {
        try {
            localStorage.setItem(THEME_KEY, theme);
        } catch (_) { /* ignore */ }
    }

    function initTheme() {
        let theme = document.documentElement.getAttribute("data-bs-theme") || "system";
        if (!VALID_THEMES.includes(theme)) theme = "system";
        applyTheme(theme);

        const media = window.matchMedia("(prefers-color-scheme: dark)");
        media.addEventListener("change", () => {
            const current = document.documentElement.getAttribute("data-bs-theme-source") || "system";
            if (current === "system") applyTheme("system");
        });
    }

    function bindRenameModal() {
        const modal = document.getElementById("renameModal");
        if (!modal) return;
        modal.addEventListener("show.bs.modal", function (event) {
            const button = event.relatedTarget;
            const project = button.getAttribute("data-project") || "";
            const title = button.getAttribute("data-digest-title") || project;
            const language = button.getAttribute("data-digest-language") || "";
            const titleInput = modal.querySelector("#renameInput");
            const languageInput = modal.querySelector("#languageInput");
            const form = modal.querySelector("#renameForm");
            if (titleInput) titleInput.value = title;
            if (languageInput) languageInput.value = language;
            if (form) form.action = "/files/" + encodeURIComponent(project) + "/rename";
        });
    }

    function bindThemeRadios() {
        document.querySelectorAll('input[name="theme"]').forEach(function (radio) {
            radio.addEventListener("change", function () {
                const value = radio.value;
                if (!VALID_THEMES.includes(value)) return;
                applyTheme(value);
                document.documentElement.setAttribute("data-bs-theme-source", value);
                persistTheme(value);
            });
        });
    }

    function bindUploadTrigger() {
        var fileInput = document.getElementById("pdfFileInput");
        var form = document.getElementById("uploadForm");
        if (!fileInput || !form) return;

        document.body.addEventListener("click", function (e) {
            var trigger = e.target.closest(".upload-trigger");
            if (!trigger) return;
            e.preventDefault();
            fileInput.click();
        });

        fileInput.addEventListener("change", function () {
            if (fileInput.files.length > 0) {
                form.submit();
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initTheme();
        bindRenameModal();
        bindThemeRadios();
        bindUploadTrigger();
    });
})();