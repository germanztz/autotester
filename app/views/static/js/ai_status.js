(function () {
    "use strict";

    const POLL_INTERVAL_MS = 1000;

    function fmtDuration(seconds) {
        if (seconds == null) return "0";
        if (seconds < 60) return seconds.toFixed(1);
        const m = Math.floor(seconds / 60);
        const s = Math.round(seconds % 60);
        return `${m}m ${s}s`;
    }

    function showWidget(state) {
        const w = document.getElementById("ai-status-widget");
        if (!w) return;
        w.classList.remove("d-none");
        w.dataset.state = state;
    }

    function hideWidget() {
        const w = document.getElementById("ai-status-widget");
        if (w) w.classList.add("d-none");
    }

    function setRunning(elapsed) {
        const running = document.getElementById("ai-status-running");
        const done = document.getElementById("ai-status-done");
        const err = document.getElementById("ai-status-error");
        running.classList.remove("d-none");
        done.classList.add("d-none");
        err.classList.add("d-none");
        const elapsedEl = document.getElementById("ai-status-elapsed");
        if (elapsedEl) elapsedEl.textContent = fmtDuration(elapsed);
    }

    function setDone(summary) {
        const running = document.getElementById("ai-status-running");
        const done = document.getElementById("ai-status-done");
        const err = document.getElementById("ai-status-error");
        running.classList.add("d-none");
        done.classList.remove("d-none");
        err.classList.add("d-none");
        document.getElementById("ai-summary-project").textContent = summary.project_name || "";
        document.getElementById("ai-summary-pages").textContent = summary.pages ?? 0;
        document.getElementById("ai-summary-chunks").textContent = summary.chunks ?? 0;
        document.getElementById("ai-summary-duration").textContent = fmtDuration(summary.duration_seconds);
    }

    function setError(msg) {
        const running = document.getElementById("ai-status-running");
        const done = document.getElementById("ai-status-done");
        const err = document.getElementById("ai-status-error");
        running.classList.add("d-none");
        done.classList.add("d-none");
        err.classList.remove("d-none");
        document.getElementById("ai-status-error-msg").textContent = msg || "Indexing failed.";
    }

    function poll(jobId) {
        const tick = async () => {
            try {
                const resp = await fetch(`/ai/status/${jobId}`, { headers: { Accept: "application/json" } });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.state === "running" || data.state === "pending") {
                    setRunning(data.elapsed);
                    setTimeout(tick, POLL_INTERVAL_MS);
                } else if (data.state === "done") {
                    setDone(data.result || {});
                } else if (data.state === "error") {
                    setError(data.error || "Indexing failed.");
                } else {
                    setError("Job not found (it may have expired).");
                }
            } catch (err) {
                setError(err.message || String(err));
            }
        };
        tick();
    }

    async function uploadWithProgress(form) {
        showWidget("running");
        setRunning(0);
        try {
            const resp = await fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                headers: { Accept: "application/json" },
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                setError(err.error || `Upload failed (HTTP ${resp.status})`);
                return;
            }
            const data = await resp.json();
            if (data.job_id) {
                poll(data.job_id);
            } else {
                setError("Server did not return a job id.");
            }
        } catch (err) {
            setError(err.message || String(err));
        }
    }

    function bindUploadForms() {
        document.querySelectorAll("form[data-async-upload]").forEach((form) => {
            form.addEventListener("submit", (e) => {
                e.preventDefault();
                const modalEl = form.closest(".modal");
                if (modalEl && window.bootstrap) {
                    const inst = window.bootstrap.Modal.getInstance(modalEl);
                    if (inst) inst.hide();
                }
                uploadWithProgress(form);
            });
        });
    }

    document.addEventListener("DOMContentLoaded", bindUploadForms);
})();