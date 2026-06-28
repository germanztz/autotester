(function () {
    "use strict";

    var POLL_INTERVAL_MS = 2000;
    var currentProject = null;
    var currentQuestion = null;
    var pollTimer = null;

    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
        });
    }

    // ----- Panel renderers -----

    function renderWelcome() {
        document.getElementById("panel-title").innerHTML =
            '<i class="bi bi-robot"></i> autotester';
        document.getElementById("panel-content").innerHTML =
            '<div class="card shadow-sm mt-3">' +
            '<div class="card-body text-center text-muted py-5">' +
            '<i class="bi bi-folder2-open d-block fs-1 mb-3"></i>' +
            '<p class="mb-0">Select a project from the sidebar to view details.</p>' +
            "</div></div>";
    }

    function renderStartingView(projectName, displayName, progressPct) {
        var pct = Math.round(progressPct || 0);
        document.getElementById("panel-title").innerHTML =
            '<i class="bi bi-file-earmark-text"></i> ' + escapeHtml(displayName);
        document.getElementById("panel-content").innerHTML =
            '<div class="card shadow-sm mt-3">' +
            '<div class="card-body">' +
            '<h6 class="card-title mb-3">Progress</h6>' +
            '<div class="progress mb-4" style="height: 24px;">' +
            '<div class="progress-bar progress-bar-striped" role="progressbar" ' +
            'style="width: ' + pct + '%;" aria-valuenow="' + pct + '" ' +
            'aria-valuemin="0" aria-valuemax="100">' + pct + '%</div>' +
            "</div>" +
            '<div id="quiz-area">' +
            '<div class="text-center py-4">' +
            '<button class="btn btn-primary btn-lg" id="startGameBtn">' +
            '<i class="bi bi-play-fill"></i> Start Game</button>' +
            "</div>" +
            "</div>" +
            '<div class="mt-3">' +
            '<button class="btn btn-outline-danger btn-sm" id="resetGameBtn">' +
            '<i class="bi bi-arrow-counterclockwise"></i> Reset progress</button>' +
            "</div>" +
            "</div></div>";
    }

    function renderGenerating() {
        var area = document.getElementById("quiz-area");
        if (!area) return;
        area.innerHTML =
            '<div class="text-center py-4">' +
            '<div class="spinner-border text-primary mb-3" role="status">' +
            '<span class="visually-hidden">Generating...</span></div>' +
            '<p class="text-muted">Generating questions from your document...</p>' +
            "</div>";
    }

    function renderQuestion(question) {
        currentQuestion = question;
        var area = document.getElementById("quiz-area");
        if (!area) return;

        var optionsHtml = "";
        if (question.type === "multiple_choice" && question.options) {
            optionsHtml = question.options.map(function (opt, i) {
                return '<button class="list-group-item list-group-item-action quiz-option" data-answer="' + escapeHtml(opt) + '">' +
                    escapeHtml(opt) + "</button>";
            }).join("");
            optionsHtml = '<div class="list-group mt-3">' + optionsHtml + "</div>";
        } else if (question.type === "true_false") {
            optionsHtml =
                '<div class="list-group mt-3">' +
                '<button class="list-group-item list-group-item-action quiz-option" data-answer="true">True</button>' +
                '<button class="list-group-item list-group-item-action quiz-option" data-answer="false">False</button>' +
                "</div>";
        } else if (question.type === "fill_blank") {
            optionsHtml =
                '<div class="input-group mt-3">' +
                '<input type="text" class="form-control" id="quizTextInput" placeholder="Type your answer..." autocomplete="off">' +
                '<button class="btn btn-primary" id="quizSubmitText">Submit</button>' +
                "</div>";
        } else if (question.type === "short_answer") {
            optionsHtml =
                '<div class="input-group mt-3">' +
                '<input type="text" class="form-control" id="quizTextInput" placeholder="Type your answer (1-3 words)..." autocomplete="off">' +
                '<button class="btn btn-primary" id="quizSubmitText">Submit</button>' +
                "</div>";
        }

        area.innerHTML =
            '<div class="quiz-question mt-3">' +
            '<div class="card">' +
            '<div class="card-body">' +
            '<p class="card-text fs-5">' + escapeHtml(question.question) + "</p>" +
            optionsHtml +
            '<div id="quizFeedback" class="mt-3"></div>' +
            "</div></div>" +
            '<div class="d-none mt-3" id="quizNextContainer">' +
            '<button class="btn btn-success" id="quizNextBtn">' +
            '<i class="bi bi-arrow-right"></i> Next</button>' +
            "</div>";
    }

    function renderFeedback(correct, correctAnswer, isMastered) {
        var fb = document.getElementById("quizFeedback");
        if (!fb) return;
        var cls = correct ? "alert-success" : "alert-danger";
        var icon = correct ? "bi-check-circle-fill" : "bi-x-circle-fill";
        var msg = correct
            ? (isMastered ? "Correct! Question mastered! " : "Correct! ")
            : "Incorrect. Correct answer: " + escapeHtml(correctAnswer);
        fb.innerHTML =
            '<div class="alert ' + cls + ' d-flex align-items-center" role="alert">' +
            '<i class="bi ' + icon + ' me-2 fs-5"></i>' +
            '<span>' + msg + "</span></div>";

        // Disable option buttons
        document.querySelectorAll(".quiz-option").forEach(function (btn) {
            btn.disabled = true;
            btn.classList.remove("active");
            if (btn.getAttribute("data-answer") === correctAnswer) {
                btn.classList.add("list-group-item-success");
            }
        });

        // Show next button
        document.getElementById("quizNextContainer").classList.remove("d-none");
    }

    function renderWaiting() {
        var area = document.getElementById("quiz-area");
        if (!area) return;
        area.innerHTML =
            '<div class="text-center py-4">' +
            '<div class="spinner-border text-info mb-3" role="status">' +
            '<span class="visually-hidden">Waiting...</span></div>' +
            '<p class="text-muted">More questions are being generated from your document...</p>' +
            "</div>";
    }

    function renderComplete(stats) {
        var area = document.getElementById("quiz-area");
        if (!area) return;
        area.innerHTML =
            '<div class="text-center py-5">' +
            '<i class="bi bi-trophy-fill text-warning display-1 mb-3"></i>' +
            '<h3 class="mb-3">Congratulations!</h3>' +
            '<p class="text-muted mb-1">You have mastered all questions!</p>' +
            '<p class="text-muted">' +
            'Total correct: ' + (stats.total_correct || 0) +
            ' | Mastered: ' + (stats.mastered_questions || 0) +
            "</p>" +
            '<button class="btn btn-outline-primary mt-2" id="resetGameBtn">' +
            '<i class="bi bi-arrow-counterclockwise"></i> Play Again</button>' +
            "</div>";
    }

    function updateProgressBar(pct) {
        var bar = document.querySelector(".progress-bar");
        if (!bar) return;
        var rounded = Math.round(pct);
        bar.style.width = rounded + "%";
        bar.textContent = rounded + "%";
        bar.setAttribute("aria-valuenow", rounded);
    }

    // ----- API calls -----

    function apiCall(method, path, body, callback) {
        var opts = {
            method: method,
            headers: { Accept: "application/json" },
        };
        if (body) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        fetch(path, opts)
            .then(function (r) { return r.json(); })
            .then(callback)
            .catch(function (err) {
                console.error("API call failed:", err);
            });
    }

    function startGame(projectName) {
        apiCall("POST", "/game/" + encodeURIComponent(projectName) + "/start", null, function (data) {
            if (data.status === "ready") {
                loadNextQuestion(projectName);
            } else {
                renderGenerating();
                pollGameStatus(projectName);
            }
        });
    }

    function loadNextQuestion(projectName) {
        apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/next", null, function (data) {
            if (data.status === "complete") {
                renderComplete(data);
                return;
            }
            if (data.status === "generating") {
                renderGenerating();
                pollGameStatus(projectName);
                return;
            }
            if (data.status === "waiting") {
                renderWaiting();
                pollGameStatus(projectName);
                return;
            }
            if (data.question) {
                renderQuestion(data);
            }
        });
    }

    function submitAnswer(projectName, answer) {
        if (!currentQuestion) return;
        apiCall("POST", "/game/" + encodeURIComponent(projectName) + "/answer", {
            para_idx: currentQuestion.para_idx,
            q_idx: currentQuestion.q_idx,
            answer: answer,
        }, function (data) {
            if (data.error) {
                console.error("Answer error:", data.error);
                return;
            }
            updateProgressBar(data.progress_pct);
            renderFeedback(data.correct, data.correct_answer, data.just_mastered);
        });
    }

    function pollGameStatus(projectName) {
        if (pollTimer) clearTimeout(pollTimer);
        apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/status", null, function (data) {
            if (data.status === "playing") {
                loadNextQuestion(projectName);
                return;
            }
            if (data.status === "ready") {
                loadNextQuestion(projectName);
                return;
            }
            if (data.status === "waiting") {
                // Digest still processing — keep polling
                pollTimer = setTimeout(function () {
                    pollGameStatus(projectName);
                }, POLL_INTERVAL_MS);
                return;
            }
            // Still generating or other — poll again
            pollTimer = setTimeout(function () {
                pollGameStatus(projectName);
            }, POLL_INTERVAL_MS);
        });
    }

    function resetGame(projectName, displayName) {
        if (!confirm("Reset game progress? All progress will be lost.")) return;
        apiCall("POST", "/game/" + encodeURIComponent(projectName) + "/reset", null, function (data) {
            if (data.status === "reset") {
                renderStartingView(projectName, displayName, 0);
            }
        });
    }

    // ----- Public API -----

    window.QuizUI = {
        selectProject: function (projectName, displayName) {
            currentProject = projectName;
            currentQuestion = null;
            if (pollTimer) {
                clearTimeout(pollTimer);
                pollTimer = null;
            }

            apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/status", null, function (data) {
                var pct = data.progress_pct || 0;
                if (data.status === "not_started") {
                    renderStartingView(projectName, displayName, 0);
                } else if (data.status === "generating") {
                    renderStartingView(projectName, displayName, pct);
                    renderGenerating();
                    pollGameStatus(projectName);
                } else if (data.status === "playing" || data.status === "waiting") {
                    renderStartingView(projectName, displayName, pct);
                    loadNextQuestion(projectName);
                } else if (data.status === "complete") {
                    renderStartingView(projectName, displayName, 100);
                    renderComplete(data);
                } else {
                    renderStartingView(projectName, displayName, 0);
                }
            });
        },

        deselectProject: function () {
            currentProject = null;
            currentQuestion = null;
            if (pollTimer) {
                clearTimeout(pollTimer);
                pollTimer = null;
            }
            renderWelcome();
        },
    };

    // ----- Event delegation -----

    document.addEventListener("DOMContentLoaded", function () {
        document.body.addEventListener("click", function (e) {
            var target = e.target;

            // Start game
            if (target.id === "startGameBtn" || target.closest("#startGameBtn")) {
                e.preventDefault();
                if (currentProject) startGame(currentProject);
                return;
            }

            // Quiz option (multiple choice / true-false)
            var option = target.closest(".quiz-option");
            if (option && currentProject && currentQuestion) {
                e.preventDefault();
                submitAnswer(currentProject, option.getAttribute("data-answer"));
                return;
            }

            // Submit text answer (fill_blank / short_answer)
            if (target.id === "quizSubmitText" || target.closest("#quizSubmitText")) {
                e.preventDefault();
                var input = document.getElementById("quizTextInput");
                if (input && input.value.trim() && currentProject && currentQuestion) {
                    submitAnswer(currentProject, input.value.trim());
                }
                return;
            }

            // Next question
            if (target.id === "quizNextBtn" || target.closest("#quizNextBtn")) {
                e.preventDefault();
                if (currentProject) loadNextQuestion(currentProject);
                return;
            }

            // Reset game
            if (target.id === "resetGameBtn" || target.closest("#resetGameBtn")) {
                e.preventDefault();
                if (currentProject) {
                    var displayName = document.querySelector(
                        '#project-list [data-project-name="' + CSS.escape(currentProject) + '"]'
                    );
                    var disp = displayName ? (displayName.dataset.digestTitle || currentProject) : currentProject;
                    resetGame(currentProject, disp);
                }
                return;
            }
        });

        // Press Enter in text input to submit
        document.body.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                var input = document.getElementById("quizTextInput");
                if (input && document.activeElement === input && currentProject && currentQuestion) {
                    e.preventDefault();
                    submitAnswer(currentProject, input.value.trim());
                }
            }
        });
    });
})();
