const state = {
  apiToken: localStorage.getItem("jobmatch_api_token") || "",
  interview: {
    target_role: "",
    skills: "",
    projects: "",
    history: [],
    currentQuestion: "",
  },
};

const titles = {
  resume: "候选人档案",
  interview: "Agent 面试",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const notice = $("#notice");
const pageTitle = $("#pageTitle");

function showNotice(message, type = "info") {
  if (!message) {
    notice.classList.add("hidden");
    notice.textContent = "";
    return;
  }
  notice.textContent = message;
  notice.dataset.type = type;
  notice.classList.remove("hidden");
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.apiToken) headers.Authorization = `Bearer ${state.apiToken}`;
  const response = await fetch(path, { headers, ...options });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    const token = window.prompt("需要 API Token（WEBUI_API_TOKEN）:");
    if (token) {
      state.apiToken = token.trim();
      localStorage.setItem("jobmatch_api_token", state.apiToken);
      return api(path, options);
    }
  }
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body;
}

function setBusy(button, busy, textWhenBusy = "处理中...") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = textWhenBusy;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function switchView(view) {
  $$(".view").forEach((node) => node.classList.toggle("active", node.id === view));
  $$(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  pageTitle.textContent = titles[view] || "AI Agent 面试机器人";
  showNotice("");
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    const online = data.status === "ok" || data.ok;
    $("#healthDot").className = online ? "dot online" : "dot offline";
    $("#healthText").textContent = online ? "online" : data.status || "degraded";
    $("#healthMeta").textContent = data.model_provider ? `模型: ${data.model_provider}` : "后端已连接";
  } catch (error) {
    $("#healthDot").className = "dot offline";
    $("#healthText").textContent = "offline";
    $("#healthMeta").textContent = error.message;
  }
}

async function generateResume(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#generateResumeBtn");
  setBusy(button, true, "生成中...");
  showNotice("");
  try {
    const result = await api("/api/generate-resume", {
      method: "POST",
      body: JSON.stringify({
        name: form.name.value,
        email: form.email.value,
        phone: form.phone.value,
        location: form.location.value,
        target_role: form.target_role.value,
        github_url: form.github_url.value,
        skills: form.skills.value,
        projects: form.projects.value,
        notes: form.notes.value,
      }),
    });
    $("#resumePreview").textContent = result.markdown || "";
    renderGaps(result.gaps || [], result.warnings || [], result.saved_path || "");
    syncInterviewDefaults(form);
    showNotice(result.saved_path ? `候选人档案已生成: ${result.saved_path}` : "候选人档案已生成");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

function renderGaps(gaps, warnings, savedPath) {
  const container = $("#resumeGaps");
  const items = [
    ...gaps.map((gap) => `<span class="chip warn">${escapeHtml(gap)}</span>`),
    ...warnings.map((warning) => `<span class="chip warn">${escapeHtml(warning)}</span>`),
  ];
  container.innerHTML = `
    ${savedPath ? `<p class="panel-hint">已保存到 ${escapeHtml(savedPath)}</p>` : ""}
    ${items.length ? `<div class="badge-cloud">${items.join("")}</div>` : ""}
  `;
}

function syncInterviewDefaults(resumeForm) {
  const interviewForm = $("#interviewSetupForm");
  if (!interviewForm) return;
  if (!interviewForm.target_role.value) interviewForm.target_role.value = resumeForm.target_role.value;
  if (!interviewForm.skills.value) interviewForm.skills.value = resumeForm.skills.value;
  if (!interviewForm.projects.value) interviewForm.projects.value = resumeForm.projects.value;
}

async function copyResume() {
  const text = $("#resumePreview").textContent.trim();
  if (!text || text.includes("生成后会在这里")) {
    showNotice("还没有可复制的候选人档案。", "error");
    return;
  }
  await navigator.clipboard.writeText(text);
  showNotice("Markdown 已复制。");
}

async function startInterview(event) {
  event.preventDefault();
  const form = event.currentTarget;
  state.interview = {
    target_role: form.target_role.value,
    skills: form.skills.value,
    projects: form.projects.value,
    history: [],
    currentQuestion: "",
  };
  $("#interviewLog").innerHTML = "";
  await requestInterviewTurn("");
}

async function sendAnswer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const answer = form.answer.value.trim();
  if (!answer) return;
  if (!state.interview.target_role) {
    showNotice("请先填写面试背景并开始面试。", "error");
    return;
  }
  appendMessage("user", answer);
  state.interview.history.push({ question: state.interview.currentQuestion, answer });
  form.answer.value = "";
  await requestInterviewTurn(answer);
}

async function requestInterviewTurn(answer) {
  const button = answer ? $("#sendAnswerBtn") : $("#startInterviewBtn");
  setBusy(button, true, answer ? "追问中..." : "出题中...");
  showNotice("");
  try {
    const result = await api("/api/interview/next", {
      method: "POST",
      body: JSON.stringify({
        target_role: state.interview.target_role,
        skills: state.interview.skills,
        projects: state.interview.projects,
        answer,
        history: state.interview.history,
      }),
    });
    if (result.feedback?.length) {
      appendMessage("agent", `反馈：${result.feedback.join(" ")}`);
    }
    const focus = result.focus?.length ? `\n关注点：${result.focus.join("、")}` : "";
    const stage = result.stage ? `「${result.stage}」` : "";
    appendMessage("agent", `第 ${result.round} 轮 ${stage}：${result.question}${focus}`);
    renderInterviewCoach(result);
    state.interview.currentQuestion = result.question;
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

function resetInterview() {
  state.interview = { target_role: "", skills: "", projects: "", history: [], currentQuestion: "" };
  $("#interviewLog").innerHTML = '<div class="message agent">填写左侧背景后开始面试。我会先确认项目真实性，再追问 Agent 编排、RAG、工具调用、评估安全和部署。</div>';
  $("#answerForm").answer.value = "";
  renderInterviewCoach({});
  showNotice("面试已重置。");
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  $("#interviewLog").appendChild(node);
  $("#interviewLog").scrollTop = $("#interviewLog").scrollHeight;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInterviewCoach(result) {
  $("#stageLabel").textContent = result.stage || "待开始";
  $("#scoreLabel").textContent = result.score ? `${result.score}/100` : "--";
  $("#answerShape").innerHTML = renderMiniList(result.answer_shape || []);
  $("#rubricList").innerHTML = renderMiniList(result.rubric || []);
  const coverage = result.coverage || [];
  $("#coverageList").innerHTML = coverage.length
    ? coverage
        .map(
          (item) =>
            `<span class="coverage-pill ${item.covered ? "covered" : ""}">${escapeHtml(item.name)}</span>`,
        )
        .join("")
    : '<span class="muted">开始后生成</span>';
}

function renderMiniList(items) {
  if (!items.length) return '<span class="muted">开始后生成</span>';
  return items.map((item) => `<span>${escapeHtml(item)}</span>`).join("");
}

function bindEvents() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  $$("[data-view-jump]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.viewJump));
  });
  $("#refreshBtn")?.addEventListener("click", checkHealth);
  $("#resumeForm")?.addEventListener("submit", generateResume);
  $("#copyResumeBtn")?.addEventListener("click", copyResume);
  $("#interviewSetupForm")?.addEventListener("submit", startInterview);
  $("#answerForm")?.addEventListener("submit", sendAnswer);
  $("#resetInterviewBtn")?.addEventListener("click", resetInterview);
}

bindEvents();
renderInterviewCoach({});
checkHealth().catch((error) => showNotice(error.message, "error"));
