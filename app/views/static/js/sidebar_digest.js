(function () {
    "use strict";

    const POLL_INTERVAL_MS = 1000;
    const POLL_INTERVAL_ERROR_MS = 4000;

    let pollTimer = null;
    let selectedProject = null;
    let lastProjectsJson = "";

    const TERMINAL_STATES = new Set(["complete", "failed", "cancelled"]);

    const STATE_ICONS = {
        queued: "bi-hourglass-split text-primary",
        processing: "bi-hourglass-split text-primary",
        complete: "bi-check2-circle text-success",
        cancelled: "bi-pause-circle text-warning",
        error: "bi-exclamation-triangle text-danger",
        failed: "bi-exclamation-octagon text-danger",
    };

    function statusText(p) {
        const tc = p.digest_total_chunks || 0;
        const cp = p.digest_chunks_processed || 0;
        const kw = p.digest_total_keywords || 0;
        switch (p.digest_state) {
            case "complete":
                return `${kw} keywords`;
            case "failed":
                return `failed`;
            case "error":
                return "Error";
            case "cancelled":
                return "cancelled";
            case "processing":
            case "queued":
                if (tc > 0) {
                    const pct = Math.min(100, Math.round((cp / tc) * 100));
                    return `processing ${pct}%`;
                }
                return "processing 0%";
            default:
                return `${p.digest_state}`;
        }
    }

    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        }[c]));
    }

    function displayName(p) {
        return p.digest_title || p.name;
    }

    function setNavbarTitle(display) {
        var npt = document.getElementById("navbar-project-title");
        if (npt) npt.textContent = " \u2014 " + display;
        document.title = "autotester \u2014 " + display;
    }

    function clearNavbarTitle() {
        var npt = document.getElementById("navbar-project-title");
        if (npt) npt.textContent = "";
        document.title = "autotester";
    }

    function selectProject(name) {
        if (selectedProject === name) {
            return;
        }
        selectedProject = name;
        document.querySelectorAll(".project-item").forEach(function (el) {
            el.classList.toggle("active", el.dataset.projectName === name);
        });
        var el = document.querySelector(
            '#project-list [data-project-name="' + CSS.escape(selectedProject) + '"]'
        );
        var display = el ? el.dataset.digestTitle : name;
        setNavbarTitle(display);
        collapseSidebar();
        if (window.QuizUI) {
            QuizUI.selectProject(name, display);
        }
    }

    window.setSelectedProject = selectProject;
    window.refreshSidebar = tick;

    function collapseSidebar() {
        var sidebar = document.getElementById("app-sidebar");
        if (sidebar) sidebar.classList.add("collapsed");
    }

    function expandSidebar() {
        var sidebar = document.getElementById("app-sidebar");
        if (sidebar) sidebar.classList.remove("collapsed");
    }

    function toggleSidebar() {
        var sidebar = document.getElementById("app-sidebar");
        if (sidebar) sidebar.classList.toggle("collapsed");
    }

    window.collapseSidebar = collapseSidebar;
    window.expandSidebar = expandSidebar;

    function restoreSelection() {
        if (!selectedProject) return;
        const el = document.querySelector(
            '#project-list [data-project-name="' + CSS.escape(selectedProject) + '"]'
        );
        if (el) {
            el.classList.add("active");
            setNavbarTitle(el.dataset.digestTitle || selectedProject);
        }
    }

    function renderRow(p) {
        const icon = STATE_ICONS[p.digest_state] || STATE_ICONS.queued;
        const status = escapeHtml(statusText(p));
        const errorClass = (p.digest_state === "error" || p.digest_state === "failed") ? "text-danger" : "";
        const showStop = ["processing", "queued"].includes(p.digest_state);
        const stopForm = showStop
            ? `<form method="POST" action="/files/${encodeURIComponent(p.name)}/cancel" class="d-inline" data-action="cancel">
                    <button type="submit" class="btn btn-sm btn-link p-1 text-warning" title="Stop digest">
                        <i class="bi bi-stop-fill"></i>
                    </button>
                </form>`
            : "";
        var disp = displayName(p);
        var game_bar = "";
        var gp = Math.min(100, Math.max(0, p.game_progress));
        if (gp > 0) {
            game_bar = `<div class="mt-1 small">
                        <div class="d-flex justify-content-between text-muted" style="font-size:0.7rem;">
                            <span>Quiz</span>
                            <span>${gp.toFixed(gp === Math.round(gp) ? 0 : 1)}%</span>
                        </div>
                        <div class="progress" style="height:4px;">
                            <div class="progress-bar bg-info" role="progressbar" style="width:${gp}%"></div>
                        </div>
                    </div>`;
        }
        return `<li class="list-group-item project-item"
                data-project-name="${escapeHtml(p.name)}"
                data-digest-title="${escapeHtml(disp)}"
                data-state="${escapeHtml(p.digest_state)}">
                <div class="d-flex align-items-center">
                    <i class="bi ${icon} me-2"></i>
                    <div class="flex-grow-1 text-truncate" title="${escapeHtml(disp)}">
                        <a href="/projects/${encodeURIComponent(p.name)}" class="text-decoration-none text-reset">
                        <div class="fw-semibold text-truncate">${escapeHtml(disp)}</div>
                    </a>
                        <div class="small text-muted project-status ${errorClass}">${status}</div>
                        ${game_bar}
                    </div>
                    <div class="project-actions">
                        ${stopForm}
                        <button type="button" class="btn btn-sm btn-link p-1"
                                data-bs-toggle="modal" data-bs-target="#renameModal"
                                data-project="${escapeHtml(p.name)}"
                                data-digest-title="${escapeHtml(disp)}"
                                data-digest-language="${escapeHtml(p.digest_language || '')}"
                                data-digest-total-words="${p.digest_total_words}"
                                data-digest-total-chunks="${p.digest_total_chunks}"
                                data-digest-total-keywords="${p.digest_total_keywords}"
                                 data-digest-total-questions="${p.digest_total_questions}"
                                 data-digest-total-rc="${p.digest_reading_check}"
                                 data-digest-total-fillgap="${p.digest_fill_gap}"
                                 data-digest-total-tf="${p.digest_true_false}"
                                 data-digest-total-errors="${p.digest_total_errors}"
                                title="Project options">
                            <i class="bi bi-pencil"></i>
                        </button>
                    </div>
                </div>
            </li>`;
    }

    function renderAll(projects) {
        const list = document.getElementById("project-list");
        if (!list) return;
        var json = JSON.stringify(projects);
        if (json === lastProjectsJson) return;
        lastProjectsJson = json;
        list.innerHTML = projects.map(renderRow).join("");
        restoreSelection();
    }

    async function tick() {
        try {
            const resp = await fetch("/ai/projects", { headers: { Accept: "application/json" } });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            renderAll(data.projects || []);
            var needsPoll = (data.projects || []).some(function (p) {
                return !TERMINAL_STATES.has(p.digest_state);
            });
            if (needsPoll) {
                pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
            } else {
                pollTimer = null;
            }
        } catch (err) {
            pollTimer = setTimeout(tick, POLL_INTERVAL_ERROR_MS);
        }
    }

    function startIfNeeded() {
        if (pollTimer) return;
        const list = document.getElementById("project-list");
        if (!list) return;
        // Always poll once per second so the user sees supervisor picks
        // and the new {x}/{y} {status} text as soon as it changes.
        tick();
    }

    document.addEventListener("DOMContentLoaded", function () {
        // Auto-collapse sidebar on small screens.
        var mobileMq = window.matchMedia("(max-width: 767px)");
        function handleMobileChange(e) {
            if (e.matches) {
                collapseSidebar();
            }
        }
        mobileMq.addEventListener("change", handleMobileChange);
        handleMobileChange(mobileMq);

        // Sidebar collapse toggle.
        document.body.addEventListener("click", function (e) {
            var toggle = e.target.closest(".sidebar-toggle");
            if (toggle) {
                e.preventDefault();
                toggleSidebar();
                return;
            }
        });

        // Project selection via event delegation on the sidebar list.
        document.body.addEventListener("click", function (e) {
            var item = e.target.closest(".project-item");
            if (!item) return;
            // Ignore clicks on action buttons inside the item.
            if (e.target.closest(".project-actions")) return;
            e.preventDefault();
            var projectName = item.dataset.projectName;
            if (selectedProject === projectName) return;
            window.location.href = "/projects/" + encodeURIComponent(projectName);
        });

        // Bind cancel forms (when present) to a no-op AJAX handler that
        // hides the row optimistically. Browser still POSTs if JS is off.
        document.body.addEventListener("submit", function (e) {
            var form = e.target;
            if (form.matches && form.matches('form[data-action="cancel"]')) {
                e.preventDefault();
                fetch(form.action, {
                    method: "POST",
                    headers: { Accept: "application/json" },
                })
                    .then(function (r) { return r.json(); })
                    .then(function () { tick(); })
                    .catch(function () { tick(); });
            }
        });

        startIfNeeded();
    });
})();