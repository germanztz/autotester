(function () {
    "use strict";

    var POLL_INTERVAL_MS = 2000;
    var currentProject = null;
    var currentDisplayName = null;
    var currentQuestion = null;
    var pollTimer = null;
    var autoAdvanceTimer = null;
    var isProcessing = false;

    function _resetUI() {
        currentQuestion = null;
        isProcessing = false;
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
        if (autoAdvanceTimer) {
            clearTimeout(autoAdvanceTimer);
            autoAdvanceTimer = null;
        }
        var cm = $("chat-messages");
        if (cm) cm.innerHTML = "";
        hideInput();
    }

    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
        });
    }

    function $(id) {
        return document.getElementById(id);
    }

    function chatScrollDown() {
        var cm = $("chat-messages");
        if (cm) cm.scrollTop = cm.scrollHeight;
    }

    // ----- Bubble rendering -----

    function addBubble(role, html) {
        var cm = $("chat-messages");
        if (!cm) return null;
        var div = document.createElement("div");
        div.className = "chat-bubble " + role;
        div.innerHTML = html;
        cm.appendChild(div);
        chatScrollDown();
        return div;
    }

    function showTyping() {
        hideTyping();
        var cm = $("chat-messages");
        if (!cm) return;
        var div = document.createElement("div");
        div.className = "chat-typing";
        div.id = "chatTypingIndicator";
        div.innerHTML =
            '<span class="small text-muted me-1">Thinking</span>' +
            '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
        cm.appendChild(div);
        chatScrollDown();
    }

    function hideTyping() {
        var el = $("chatTypingIndicator");
        if (el) el.remove();
    }

    // ----- Input bar -----

    function renderMCInput(options) {
        var inner = $("chat-input-inner");
        if (!inner) return;
        inner.innerHTML = options.map(function (opt) {
            return '<button class="btn btn-outline-primary chat-option-btn" data-answer="' + escapeHtml(opt) + '">' + escapeHtml(opt) + "</button>";
        }).join("");
    }

    function renderTextInput(placeholder) {
        var inner = $("chat-input-inner");
        if (!inner) return;
        inner.innerHTML =
            '<input type="text" class="form-control chat-text-input" id="chatTextInput" placeholder="' + escapeHtml(placeholder) + '" autocomplete="off">' +
            '<button class="btn btn-primary chat-text-submit" id="chatTextSubmit">Submit</button>';
        var inp = $("chatTextInput");
        if (inp) inp.focus();
    }

    function disableInput() {
        var inner = $("chat-input-inner");
        if (!inner) return;
        inner.querySelectorAll("button, input").forEach(function (el) {
            el.disabled = true;
        });
    }

    function renderInput(type, options) {
        var bar = $("chat-input-bar");
        if (!bar) return;
        bar.classList.remove("d-none");
        if (type === "multiple_choice" || type === "info" || type === "fill" || type === "true_false") {
            renderMCInput(options);
        } else if (type === "fill_blank") {
            renderTextInput("Type your answer...");
        } else if (type === "short_answer") {
            renderTextInput("Type your answer (1-3 words)...");
        }
    }

    function hideInput() {
        var bar = $("chat-input-bar");
        if (bar) bar.classList.add("d-none");
    }

    // ----- Welcome / Starting view -----

    function renderWelcome() {
        hideInput();
        var cm = $("chat-messages");
        if (!cm) return;
        cm.innerHTML =
            '<div class="text-center text-muted py-5" id="welcome-placeholder">' +
            '<i class="bi bi-folder2-open d-block fs-1 mb-3"></i>' +
            '<p class="mb-0">Select a project from the sidebar to view details.</p>' +
            "</div>";
    }

    function renderStartView(projectName, displayName) {
        var cm = $("chat-messages");
        if (cm) cm.innerHTML = "";
        addBubble("bot",
            '<p class="mb-2">Ready to test your knowledge on <strong>' + escapeHtml(displayName) + '</strong>?</p>'
        );
        var inner = $("chat-input-inner");
        if (inner) {
            inner.innerHTML = '<button class="btn btn-primary" id="startGameBtn">' +
                '<i class="bi bi-play-fill"></i> Start Game</button>';
        }
        var bar = $("chat-input-bar");
        if (bar) bar.classList.remove("d-none");
    }

    function renderCompleteContent(stats) {
        hideInput();
        addBubble("bot",
            '<div class="text-center py-2">' +
            '<i class="bi bi-trophy-fill text-warning d-block fs-1 mb-2"></i>' +
            '<h5 class="mb-2">Congratulations!</h5>' +
            '<p class="mb-1 text-muted">You have mastered all questions!</p>' +
            '<p class="small text-muted">' +
            "Correct: " + (stats.total_correct || 0) +
            " | Mastered: " + (stats.mastered_questions || 0) +
            "</p>" +
            '<button class="btn btn-outline-primary mt-1" id="playAgainBtn">' +
            '<i class="bi bi-arrow-counterclockwise"></i> Play Again</button>' +
            "</div>"
        );
    }

    // ----- History reconstruction -----

    function renderHistoryItem(item) {
        if (item.title) {
            addBubble("title", "<strong>" + escapeHtml(item.title) + "</strong>");
        }
        addBubble("bot", "<strong>" + escapeHtml(item.question_text) + "</strong>");
        addBubble("user", escapeHtml(item.last_answer));
        var cls = item.last_answer_correct ? "correct" : "incorrect";
        var icon = item.last_answer_correct ? "bi-check-circle-fill" : "bi-x-circle-fill";
        var answerText = Array.isArray(item.correct_answer) ? item.correct_answer.join(", ") : item.correct_answer;
        var msg = item.last_answer_correct
            ? "Correct!"
            : "Incorrect. Correct answer: " + escapeHtml(answerText);
        var bubble = addBubble("feedback", '<i class="bi ' + icon + ' feedback-icon"></i> ' + msg);
        if (bubble) bubble.classList.add(cls);
    }

    function loadHistoryAndResume(projectName, displayName, statusData) {
        apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/history", null, function (hdata) {
            var history = hdata.history || [];
            if (history.length > 0) {
                history.forEach(function (item) {
                    renderHistoryItem(item);
                });
                if (statusData.total_questions > 0) {
                    addBubble("bot",
                        'Resuming &mdash; you\'ve answered <strong>' +
                        (statusData.total_correct || 0) + "/" + (statusData.total_possible || 0) +
                        "</strong> (" + Math.round(statusData.progress_pct || 0) + "%), " +
                        (statusData.mastered_questions || 0) + " mastered."
                    );
                }
            } else {
                if (statusData.total_questions > 0) {
                    addBubble("bot",
                        'Resuming &mdash; you\'ve answered <strong>' +
                        (statusData.total_correct || 0) + "/" + (statusData.total_possible || 0) +
                        "</strong> (" + Math.round(statusData.progress_pct || 0) + "%), " +
                        (statusData.mastered_questions || 0) + " mastered."
                    );
                }
            }
            if (statusData.status === "complete") {
                renderCompleteContent(statusData);
            } else {
                loadNextQuestion(projectName);
            }
        });
    }

    // ----- Question / Answer flow -----

    function renderQuestion(q) {
        currentQuestion = q;
        if (q.title) {
            addBubble("title", "<strong>" + escapeHtml(q.title) + "</strong>");
        }
        addBubble("bot", "<strong>" + escapeHtml(q.question) + "</strong>");
        renderInput(q.type, q.options);
    }

    function renderFeedback(data) {
        var correct = data.correct;
        var correctAnswer = data.correct_answer;
        var isMastered = data.just_mastered;
        var paraIdx = data.para_idx;
        var qIdx = data.q_idx;
        var paraJustCompleted = data.para_just_completed;
        var nextParaUnlocked = data.next_para_unlocked;

        var cls = correct ? "correct" : "incorrect";
        var icon = correct ? "bi-check-circle-fill" : "bi-x-circle-fill";
        var answerText = Array.isArray(correctAnswer) ? correctAnswer.join(", ") : correctAnswer;

        var parts = [];
        if (correct) {
            parts.push("The question " + (qIdx + 1) + " of the paragraph " + (paraIdx + 1) + " is Correct!");
            if (isMastered) parts.push("Question mastered!");
            if (paraJustCompleted) parts.push("You mastered the paragraph " + (paraIdx + 1) + " too!");
            if (nextParaUnlocked) parts.push("Paragraph " + (nextParaUnlocked === true ? (paraIdx + 2) : nextParaUnlocked) + " unlocked!");
        } else {
            parts.push("The question " + (qIdx + 1) + " of the paragraph " + (paraIdx + 1) + " is Incorrect.");
            parts.push("Correct answer: " + escapeHtml(answerText));
        }

        var msg = parts.join(" ");
        var bubble = addBubble("feedback", '<i class="bi ' + icon + ' feedback-icon"></i> ' + msg);
        if (bubble) bubble.classList.add(cls);
    }

    function submitAnswer(projectName, answer) {
        if (!currentQuestion || isProcessing) return;
        isProcessing = true;
        disableInput();
        addBubble("user", escapeHtml(answer));
        apiCall("POST", "/game/" + encodeURIComponent(projectName) + "/answer", {
            para_idx: currentQuestion.para_idx,
            q_idx: currentQuestion.q_idx,
            answer: answer,
        }, function (data) {
            if (data.error) {
                console.error("Answer error:", data.error);
                isProcessing = false;
                return;
            }
            if (window.refreshSidebar) window.refreshSidebar();
            renderFeedback(data);
            var delay = data.correct ? 1500 : 2000;
            autoAdvanceTimer = setTimeout(function () {
                autoAdvanceTimer = null;
                loadNextQuestion(projectName);
            }, delay);
        });
    }

    function loadNextQuestion(projectName) {
        hideTyping();
        isProcessing = false;
        showTyping();
        apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/next", null, function (data) {
            hideTyping();
            if (data.status === "complete") {
                renderCompleteContent(data);
                return;
            }
            if (data.status === "generating" || data.status === "waiting") {
                showTyping();
                pollGameStatus(projectName);
                return;
            }
            if (data.question) {
                renderQuestion(data);
            }
        });
    }

    function startGame(projectName) {
        hideInput();
        apiCall("POST", "/game/" + encodeURIComponent(projectName) + "/start", null, function (data) {
            showTyping();
            if (data.status === "ready") {
                loadNextQuestion(projectName);
            } else {
                pollGameStatus(projectName);
            }
        });
    }

    // ----- Polling -----

    function pollGameStatus(projectName) {
        if (pollTimer) clearTimeout(pollTimer);
        apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/status", null, function (data) {
            if (data.status === "playing" || data.status === "ready") {
                loadNextQuestion(projectName);
                return;
            }
            if (data.status === "waiting") {
                pollTimer = setTimeout(function () {
                    pollGameStatus(projectName);
                }, POLL_INTERVAL_MS);
                return;
            }
            pollTimer = setTimeout(function () {
                pollGameStatus(projectName);
            }, POLL_INTERVAL_MS);
        });
    }

    function resetGame(projectName) {
        if (!confirm("Reset game progress? All progress will be lost.")) return;
        apiCall("POST", "/game/" + encodeURIComponent(projectName) + "/reset", null, function (data) {
            if (data.status === "reset") {
                if (window.refreshSidebar) window.refreshSidebar();
                _resetUI();
                renderStartView(projectName, currentDisplayName);
            }
        });
    }

    // ----- API helper -----

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

    // ----- Public API -----

    window.QuizUI = {
        selectProject: function (projectName, displayName) {
            currentProject = projectName;
            currentDisplayName = displayName;
            _resetUI();

            apiCall("GET", "/game/" + encodeURIComponent(projectName) + "/status", null, function (data) {
                if (data.status === "not_started") {
                    renderStartView(projectName, displayName);
                } else if (data.status === "generating") {
                    showTyping();
                    pollGameStatus(projectName);
                } else if (data.status === "playing" || data.status === "waiting") {
                    loadHistoryAndResume(projectName, displayName, data);
                } else if (data.status === "complete") {
                    loadHistoryAndResume(projectName, displayName, data);
                } else {
                    renderStartView(projectName, displayName);
                }
            });
        },

        deselectProject: function () {
            currentProject = null;
            currentDisplayName = null;
            _resetUI();
            renderWelcome();
        },
    };

    // ----- Event delegation -----

    document.addEventListener("DOMContentLoaded", function () {
        document.body.addEventListener("click", function (e) {
            var target = e.target;

            if (target.id === "startGameBtn" || target.closest("#startGameBtn")) {
                e.preventDefault();
                if (currentProject) startGame(currentProject);
                return;
            }

            if (target.id === "playAgainBtn" || target.closest("#playAgainBtn")) {
                e.preventDefault();
                if (currentProject) resetGame(currentProject);
                return;
            }

            var optBtn = target.closest(".chat-option-btn");
            if (optBtn && currentProject && currentQuestion && !optBtn.disabled) {
                e.preventDefault();
                submitAnswer(currentProject, optBtn.getAttribute("data-answer"));
                return;
            }

            if (target.id === "chatTextSubmit" || target.closest("#chatTextSubmit")) {
                e.preventDefault();
                var input = $("chatTextInput");
                if (input && input.value.trim() && currentProject && currentQuestion && !isProcessing) {
                    submitAnswer(currentProject, input.value.trim());
                }
                return;
            }

            var modalResetBtn = target.closest(".reset-progress-btn");
            if (modalResetBtn) {
                e.preventDefault();
                var proj = modalResetBtn.dataset.project;
                if (proj && confirm("Reset game progress for this project? All progress will be lost.")) {
                    apiCall("POST", "/game/" + encodeURIComponent(proj) + "/reset", null, function (data) {
                        if (data.status === "reset") {
                            if (window.refreshSidebar) window.refreshSidebar();
                            var m = bootstrap.Modal.getInstance(document.getElementById("renameModal"));
                            if (m) m.hide();
                            if (proj === currentProject) {
                                _resetUI();
                                renderStartView(proj, currentDisplayName);
                            }
                        }
                    });
                }
                return;
            }
        });

        document.body.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                var input = $("chatTextInput");
                if (input && document.activeElement === input && currentProject && currentQuestion && !isProcessing) {
                    e.preventDefault();
                    submitAnswer(currentProject, input.value.trim());
                }
            }
        });
    });
})();
