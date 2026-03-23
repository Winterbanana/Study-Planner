function getOne(selector, root) {
	return (root || document).querySelector(selector);
}

function getAll(selector, root) {
	return Array.from((root || document).querySelectorAll(selector));
}

function togglePasswordInput(input, button) {
	const showPassword = input.type === "password";
	const eyeOpen = getOne(".eye-open", button);
	const eyeClosed = getOne(".eye-closed", button);

	input.type = showPassword ? "text" : "password";
	button.setAttribute("aria-label", showPassword ? "Hide password" : "Show password");
	button.setAttribute("title", showPassword ? "Hide password" : "Show password");

	if (eyeOpen && eyeClosed) {
		eyeOpen.style.display = showPassword ? "none" : "inline-flex";
		eyeClosed.style.display = showPassword ? "inline-flex" : "none";
	}
}

function setPriorityBadge(priorityElement, priorityValue) {
	const priority = (priorityValue || "Medium").trim();
	const safePriority = priority.toLowerCase();

	priorityElement.classList.remove("priority-low", "priority-medium", "priority-high");
	if (safePriority === "low") {
		priorityElement.classList.add("priority-low");
	} else if (safePriority === "high") {
		priorityElement.classList.add("priority-high");
	} else {
		priorityElement.classList.add("priority-medium");
	}

	priorityElement.textContent = `${priority} Priority`;
}

function openJournalEntry(card, modal, titleElement, metaElement, contentElement, priorityElement) {
	titleElement.textContent = card.getAttribute("data-journal-title") || "Journal Entry";
	contentElement.textContent = card.getAttribute("data-journal-content") || "No content available.";

	const date = card.getAttribute("data-journal-date") || "";
	const mood = card.getAttribute("data-journal-mood") || "";
	metaElement.textContent = mood ? `${date} | ${mood}` : date;

	setPriorityBadge(priorityElement, card.getAttribute("data-journal-priority") || "Medium");
	modal.show();
}

function buildQuizQuestionCard(index) {
	return `
		<article class="quiz-builder-card">
			<h4>Question ${index}</h4>
			<label for="q_text_${index}">Question ${index}</label>
			<input id="q_text_${index}" type="text" name="q_text_${index}" required>
			<div class="row g-2">
				<div class="col-md-6"><input type="text" name="q_a_${index}" placeholder="Option A" required></div>
				<div class="col-md-6"><input type="text" name="q_b_${index}" placeholder="Option B" required></div>
			</div>
			<div class="row g-2">
				<div class="col-md-6"><input type="text" name="q_c_${index}" placeholder="Option C" required></div>
				<div class="col-md-6"><input type="text" name="q_d_${index}" placeholder="Option D" required></div>
			</div>
			<label for="q_correct_${index}">Correct Answer</label>
			<select id="q_correct_${index}" name="q_correct_${index}" required>
				<option value="A">A</option>
				<option value="B">B</option>
				<option value="C">C</option>
				<option value="D">D</option>
			</select>
		</article>
	`;
}

function initSmoothMotion() {
	if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
		return;
	}

	const revealTargets = getAll(
		".panel, .section-head, .metric-card, .course-card, .assignment-card, .journal-item, .quiz-item, .grouping-item, .quick-actions .btn"
	);
	if (!revealTargets.length) {
		return;
	}

	revealTargets.forEach(function (element, index) {
		element.classList.add("reveal");
		element.style.setProperty("--reveal-delay", `${Math.min(index * 35, 420)}ms`);
	});

	const observer = new IntersectionObserver(
		function (entries, activeObserver) {
			entries.forEach(function (entry) {
				if (!entry.isIntersecting) {
					return;
				}

				entry.target.classList.add("is-visible");
				activeObserver.unobserve(entry.target);
			});
		},
		{ threshold: 0.12 }
	);

	revealTargets.forEach(function (element) {
		observer.observe(element);
	});
}

function initQuizTimer() {
	const timerElement = getOne("[data-quiz-timer]");
	if (!timerElement) {
		return;
	}

	const quizForm = getOne("[data-quiz-form]");
	const startButton = getOne("[data-quiz-start]");
	const startState = document.getElementById("quiz-start-state");
	const addQuestionPanel = getOne("[data-add-question-panel]");

	let remainingSeconds = Math.max(0, Number(timerElement.getAttribute("data-minutes") || "0") * 60);
	let timerId = null;
	let quizStarted = false;

	function renderTimer() {
		const minutes = Math.floor(remainingSeconds / 60).toString().padStart(2, "0");
		const seconds = (remainingSeconds % 60).toString().padStart(2, "0");
		timerElement.textContent = `Time left: ${minutes}:${seconds}`;
	}

	function stopTimer() {
		if (!timerId) {
			return;
		}
		window.clearInterval(timerId);
		timerId = null;
	}

	function startTimer() {
		if (timerId || remainingSeconds <= 0) {
			return;
		}

		timerElement.classList.remove("timer-paused");
		timerId = window.setInterval(function () {
			remainingSeconds -= 1;
			renderTimer();
			if (remainingSeconds > 0) {
				return;
			}

			stopTimer();
			if (quizForm) {
				quizForm.submit();
			}
		}, 1000);
	}

	function pauseTimer() {
		stopTimer();
		timerElement.classList.add("timer-paused");
	}

	if (startButton) {
		startButton.addEventListener("click", function () {
			quizStarted = true;
			if (startState) {
				startState.style.display = "none";
			}
			if (quizForm) {
				quizForm.style.display = "";
			}
			renderTimer();
			startTimer();
		});
	}

	if (addQuestionPanel) {
		addQuestionPanel.addEventListener("focusin", function () {
			if (quizStarted) {
				pauseTimer();
			}
		});

		addQuestionPanel.addEventListener("focusout", function (event) {
			if (!quizStarted || addQuestionPanel.contains(event.relatedTarget)) {
				return;
			}
			startTimer();
		});
	}
}

function initPasswordToggles() {
	getAll(".icon-toggle[data-target]").forEach(function (button) {
		const targetId = button.getAttribute("data-target");
		const input = targetId ? document.getElementById(targetId) : null;
		if (!input) {
			return;
		}

		button.addEventListener("click", function () {
			togglePasswordInput(input, button);
		});
	});
}

function initAuthInvalidMotion() {
	getAll(".auth-form").forEach(function (form) {
		form.addEventListener(
			"invalid",
			function (event) {
				const field = event.target;
				if (!(field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement)) {
					return;
				}

				field.classList.remove("field-invalid");
				void field.offsetWidth;
				field.classList.add("field-invalid");
			},
			true
		);

		form.addEventListener("input", function (event) {
			const field = event.target;
			if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement) {
				field.classList.remove("field-invalid");
			}
		});
	});
}

function initActivityGroupingCourseSync() {
	const groupingSelect = document.getElementById("activity_grouping_id");
	const courseSelect = document.getElementById("course_id");
	if (!groupingSelect || !courseSelect) {
		return;
	}

	const originalOptions = Array.from(courseSelect.options).map(function (option) {
		return option.cloneNode(true);
	});

	function renderCourseOptions() {
		const selectedGrouping = groupingSelect.value;
		const previousValue = courseSelect.value;

		courseSelect.innerHTML = "";
		originalOptions.forEach(function (option, index) {
			const optionGroupingId = option.getAttribute("data-grouping-id") || "";
			if (index === 0 || !selectedGrouping || optionGroupingId === selectedGrouping) {
				courseSelect.appendChild(option.cloneNode(true));
			}
		});

		const hasPreviousValue = Array.from(courseSelect.options).some(function (option) {
			return option.value === previousValue;
		});
		courseSelect.value = hasPreviousValue ? previousValue : "";
	}

	groupingSelect.addEventListener("change", renderCourseOptions);
	renderCourseOptions();
}

function initQuickFillButtons() {
	getAll("[data-fill-target][data-fill-value]").forEach(function (button) {
		button.addEventListener("click", function () {
			const targetId = button.getAttribute("data-fill-target");
			const target = targetId ? document.getElementById(targetId) : null;
			if (!target) {
				return;
			}

			target.value = button.getAttribute("data-fill-value") || "";
			target.dispatchEvent(new Event("input", { bubbles: true }));
			target.focus();
		});
	});
}

function initJournalEntryModal() {
	const modalElement = document.getElementById("journalEntryModal");
	const cards = getAll(".journal-trigger");
	if (!modalElement || !cards.length || typeof bootstrap === "undefined") {
		return;
	}

	const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
	const titleElement = document.getElementById("journalModalTitle");
	const metaElement = getOne("[data-journal-modal-meta]", modalElement);
	const contentElement = getOne("[data-journal-modal-content]", modalElement);
	const priorityElement = getOne("[data-journal-modal-priority]", modalElement);

	cards.forEach(function (card) {
		card.addEventListener("click", function () {
			openJournalEntry(card, modal, titleElement, metaElement, contentElement, priorityElement);
		});

		card.addEventListener("keydown", function (event) {
			if (event.key !== "Enter" && event.key !== " ") {
				return;
			}
			event.preventDefault();
			openJournalEntry(card, modal, titleElement, metaElement, contentElement, priorityElement);
		});
	});
}

function initToggleTargets() {
	getAll("[data-toggle-target]").forEach(function (button) {
		button.addEventListener("click", function () {
			const targetId = button.getAttribute("data-toggle-target");
			const target = targetId ? document.getElementById(targetId) : null;
			if (!target) {
				return;
			}

			const isHidden = window.getComputedStyle(target).display === "none";
			target.style.display = isHidden ? "grid" : "none";
		});
	});
}

function initQuizBuilderModal() {
	const form = getOne("[data-quiz-builder-form]");
	const countSelect = getOne("[data-quiz-question-count]");
	const questionsContainer = getOne("[data-quiz-questions-container]");
	const modalElement = document.getElementById("createQuizModal");
	if (!form || !countSelect || !questionsContainer) {
		return;
	}

	const maxQuestions = Number(questionsContainer.getAttribute("data-max-questions") || "10");
	const defaultCount = Number(countSelect.value || "3");

	function renderQuestionCards() {
		const selectedCount = Number(countSelect.value || defaultCount);
		const safeCount = Math.min(Math.max(selectedCount, 1), maxQuestions);
		const cards = [];

		for (let index = 1; index <= safeCount; index += 1) {
			cards.push(buildQuizQuestionCard(index));
		}

		questionsContainer.innerHTML = cards.join("");
	}

	countSelect.addEventListener("change", renderQuestionCards);
	renderQuestionCards();

	if (modalElement) {
		modalElement.addEventListener("hidden.bs.modal", function () {
			form.reset();
			countSelect.value = String(defaultCount);
			renderQuestionCards();
		});
	}
}

document.addEventListener("DOMContentLoaded", function () {
	initSmoothMotion();
	initQuizTimer();
	initPasswordToggles();
	initAuthInvalidMotion();
	initActivityGroupingCourseSync();
	initQuickFillButtons();
	initJournalEntryModal();
	initToggleTargets();
	initQuizBuilderModal();
});