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

    function selectProject(name) {
        if (selectedProject === name) {
            // Toggle off when clicking the same project.
            selectedProject = null;
            document.querySelectorAll(".project-item").forEach(function (el) {
                el.classList.remove("active");
            });
            document.getElementById("panel-title").innerHTML =
                '<i class="bi bi-robot"></i> autotester';
            document.getElementById("panel-content").innerHTML =
                '<div class="card shadow-sm mt-3">' +
                '<div class="card-body text-center text-muted py-5">' +
                '<i class="bi bi-folder2-open d-block fs-1 mb-3"></i>' +
                '<p class="mb-0">Select a project from the sidebar to view details.</p>' +
                "</div></div>";
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
        document.getElementById("panel-title").innerHTML =
            '<i class="bi bi-file-earmark-text"></i> ' + escapeHtml(display);
        document.getElementById("panel-content").innerHTML =
            '<div class="card shadow-sm mt-3">' +
            '<div class="card-body">' +
            '<p class="text-muted mb-0">Project <strong>' + escapeHtml(display) +
            "</strong> selected.</p></div></div>";
    }

    function restoreSelection() {
        if (!selectedProject) return;
        const el = document.querySelector(
            '#project-list [data-project-name="' + CSS.escape(selectedProject) + '"]'
        );
        if (el) el.classList.add("active");
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
        return `
            <li class="list-group-item project-item"
                data-project-name="${escapeHtml(p.name)}"
                data-digest-title="${escapeHtml(disp)}"
                data-state="${escapeHtml(p.digest_state)}">
                <div class="d-flex align-items-center">
                    <i class="bi ${icon} me-2"></i>
                    <div class="flex-grow-1 text-truncate" title="${escapeHtml(disp)}">
                        <div class="fw-semibold text-truncate">${escapeHtml(disp)}</div>
                        <div class="small text-muted project-status ${errorClass}">${status}</div>
                    </div>
                    <div class="project-actions">
                        ${stopForm}
                        <button type="button" class="btn btn-sm btn-link p-1"
                                data-bs-toggle="modal" data-bs-target="#renameModal"
                                data-project="${escapeHtml(p.name)}"
                                data-digest-title="${escapeHtml(disp)}"
                                data-digest-language="${escapeHtml(p.digest_language || '')}"
                                title="Project options">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <form method="POST" action="/files/${encodeURIComponent(p.name)}/delete"
                              class="d-inline"
                              onsubmit="return confirm('Delete project ${escapeHtml(p.name)}?');">
                            <button type="submit" class="btn btn-sm btn-link p-1 text-danger" title="Delete">
                                <i class="bi bi-trash"></i>
                            </button>
                        </form>
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
        // Project selection via event delegation on the sidebar list.
        document.body.addEventListener("click", function (e) {
            var item = e.target.closest(".project-item");
            if (!item) return;
            // Ignore clicks on action buttons inside the item.
            if (e.target.closest(".project-actions")) return;
            selectProject(item.dataset.projectName);
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