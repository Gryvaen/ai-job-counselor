const state = {
  health: null,
  config: null,
  dashboard: null,
  jobs: [],
  versions: [],
  selectedJobId: null,
  selectedVersionId: null,
};

const titles = {
  dashboard: "概览",
  chat: "对话助手",
  profile: "我的简历",
  search: "岗位搜索",
  matches: "匹配结果",
  versions: "简历版本",
  settings: "设置",
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
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || "请求失败");
  }
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
  pageTitle.textContent = titles[view] || "JobMatch";
  showNotice("");

  if (view === "matches") loadJobs();
  if (view === "versions") loadVersions();
  if (view === "profile") loadProfile();
  if (view === "settings") loadConfig();
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    state.health = data;
    $("#healthDot").className = "dot online";
    $("#healthText").textContent = "online";
    $("#healthMeta").textContent = data.boss_login_exists ? "Boss 登录态存在" : "Boss 未登录";
  } catch (error) {
    $("#healthDot").className = "dot offline";
    $("#healthText").textContent = "offline";
    $("#healthMeta").textContent = error.message;
  }
  renderSettings();
}

async function loadConfig() {
  const config = await api("/api/config");
  state.config = config;
  renderConfigForm(config);
  renderSettings();
}

function renderConfigForm(config) {
  const form = $("#configForm");
  if (!form) return;
  Object.entries(config).forEach(([key, value]) => {
    if (form.elements[key]) {
      form.elements[key].value = value ?? "";
    }
  });
}

async function saveConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#saveConfigBtn");
  setBusy(button, true, "保存中...");
  try {
    const payload = {};
    Array.from(form.elements).forEach((element) => {
      if (!element.name) return;
      payload[element.name] = element.type === "number" ? Number(element.value) : element.value.trim();
    });
    const result = await api("/api/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.config = result.config;
    renderConfigForm(result.config);
    await checkHealth();
    showNotice(result.message || "配置已保存");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  state.dashboard = data;
  $("#metricJobs").textContent = data.metrics.jobs;
  $("#metricMatches").textContent = data.metrics.matches;
  $("#metricResumes").textContent = data.metrics.resumes;
  $("#metricPlans").textContent = data.metrics.plans;
  renderJobList($("#latestJobs"), data.latest_jobs || [], { compact: true });
}

async function loadProfile() {
  const profile = await api("/api/resume-profile");
  const form = $("#profileForm");
  const base = profile.profile || {};
  const preferences = profile.preferences || {};
  form.name.value = base.name || profile.name || "";
  form.location.value = base.location || preferences.city || "";
  form.email.value = base.email || "";
  form.phone.value = base.phone || "";
  form.skills.value = arrayText(profile.skills);
  form.target_roles.value = arrayText(preferences.target_roles || []);
  form.cities.value = arrayText(preferences.cities || (preferences.city ? [preferences.city] : []));
  form.projects.value = JSON.stringify(profile.projects || [], null, 2);
  form.experience.value = JSON.stringify(profile.experience || [], null, 2);
}

async function saveProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#saveProfileBtn");
  setBusy(button, true, "保存中...");
  try {
    const profile = {
      profile: {
        name: form.name.value.trim(),
        email: form.email.value.trim(),
        phone: form.phone.value.trim(),
        location: form.location.value.trim(),
      },
      skills: parseList(form.skills.value),
      projects: parseJsonField(form.projects.value, "项目经历 JSON"),
      experience: parseJsonField(form.experience.value, "工作/实习经历 JSON"),
      education: [],
      preferences: {
        cities: parseList(form.cities.value),
        city: parseList(form.cities.value)[0] || form.location.value.trim(),
        target_roles: parseList(form.target_roles.value),
        keywords: parseList(form.target_roles.value),
        salary_range: "",
      },
      constraints: {
        do_not_invent: true,
        must_mark_uncertain: true,
      },
    };
    const result = await api("/api/resume-profile", {
      method: "PUT",
      body: JSON.stringify({ profile }),
    });
    showNotice(`已保存到 ${result.path}`);
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function generateTemplate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const profileForm = $("#profileForm");
  const button = $("#generateTemplateBtn");
  setBusy(button, true, "生成中...");
  try {
    const payload = {
      name: profileForm.name.value,
      email: profileForm.email.value,
      phone: profileForm.phone.value,
      location: profileForm.location.value,
      skills: profileForm.skills.value,
      target_role: form.target_role.value,
      github_url: form.github_url.value,
      notes: form.notes.value,
    };
    const result = await api("/api/generate-resume", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("#versionPreview").textContent = result.markdown;
    switchView("versions");
    showNotice(`模板已生成: ${result.saved_path}`);
    await loadVersions();
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function runSearch(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#searchBtn");
  const output = $("#searchResult");
  setBusy(button, true, "搜索中...");
  output.textContent = "正在调用 Boss 搜索、RAG 检索、匹配评分和简历优化。这个步骤可能需要一些时间。";
  try {
    const result = await api("/api/jobs/search", {
      method: "POST",
      body: JSON.stringify({
        keywords: form.keywords.value,
        threshold: Number(form.threshold.value || 75),
      }),
    });
    output.innerHTML = `
      <strong>${escapeHtml(result.message)}</strong><br>
      抓取岗位: ${result.jobs_scraped}<br>
      完成匹配: ${result.matches_scored}<br>
      生成简历: ${result.resumes_generated}<br>
      通知数量: ${result.notified}
    `;
    state.jobs = result.jobs || [];
    renderJobList($("#jobList"), state.jobs);
    await loadDashboard();
    switchView("matches");
  } catch (error) {
    output.textContent = error.message;
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function loadJobs() {
  const data = await api("/api/jobs");
  state.jobs = data.jobs || [];
  renderJobList($("#jobList"), state.jobs);
}

function renderJobList(container, jobs, options = {}) {
  if (!container) return;
  if (!jobs.length) {
    container.className = "job-list empty";
    container.textContent = "暂无岗位记录";
    return;
  }

  container.className = "job-list";
  container.innerHTML = jobs
    .map((job) => {
      const match = job.match || {};
      const score = Number(match.score || 0);
      const chips = [
        job.city,
        job.salary,
        match.suggestion,
        job.resume ? `简历: ${job.resume.status || "draft"}` : "",
      ]
        .filter(Boolean)
        .map((item) => `<span class="chip">${escapeHtml(item)}</span>`)
        .join("");
      return `
        <button class="job-card ${state.selectedJobId === job.id ? "active" : ""}" type="button" data-job-id="${escapeAttr(job.id)}">
          <span class="job-title">
            <span>${escapeHtml(job.title)} @ ${escapeHtml(job.company)}</span>
            <span class="score">${score}</span>
          </span>
          <span class="job-meta">${chips}</span>
          ${options.compact ? "" : `<span class="muted">${escapeHtml((match.reasoning || job.description || "").slice(0, 96))}</span>`}
        </button>
      `;
    })
    .join("");
}

async function selectJob(jobId) {
  state.selectedJobId = jobId;
  renderJobList($("#jobList"), state.jobs);
  const data = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
  renderJobDetail(data);
}

function renderJobDetail(data) {
  const job = data.job;
  const match = data.match || {};
  const resume = data.resume;
  const plan = data.learning_plan;
  $("#jobDetail").innerHTML = `
    <div class="detail-header">
      <div>
        <h2>${escapeHtml(job.title)} @ ${escapeHtml(job.company)}</h2>
        <div class="chip-row">
          <span class="chip">${escapeHtml(job.city || "城市未知")}</span>
          <span class="chip">${escapeHtml(job.salary || "薪资未知")}</span>
          <span class="chip">匹配 ${Number(match.score || 0)}</span>
          ${match.suggestion ? `<span class="chip">${escapeHtml(match.suggestion)}</span>` : ""}
        </div>
      </div>
      <button id="jobResumeBtn" type="button" data-job-id="${escapeAttr(job.id)}">生成定制简历</button>
    </div>

    <section class="detail-section">
      <h3>匹配解释</h3>
      <p>${escapeHtml(match.reasoning || "暂无匹配解释")}</p>
    </section>

    <section class="detail-section">
      <h3>优势</h3>
      ${listHtml(match.advantages || [], "暂无优势记录")}
    </section>

    <section class="detail-section">
      <h3>缺口</h3>
      ${listHtml(match.missing || [], "暂无缺口记录")}
    </section>

    <section class="detail-section">
      <h3>RAG 证据</h3>
      ${listHtml(match.rag_evidence || [], "暂无证据")}
    </section>

    <section class="detail-section">
      <h3>简历版本</h3>
      <p>${resume ? `版本 #${resume.id} · ${escapeHtml(resume.status)} · ${escapeHtml(resume.file_path || "DB")}` : "尚未生成"}</p>
    </section>

    <section class="detail-section">
      <h3>学习计划</h3>
      <p>${plan ? `${plan.estimated_hours} 小时 · ${(plan.priority_skills || []).map(escapeHtml).join("、")}` : "尚未生成"}</p>
    </section>

    <section class="detail-section">
      <h3>JD 原文</h3>
      <p class="job-desc">${escapeHtml(job.description || "暂无 JD")}</p>
    </section>
  `;
}

async function generateForSelectedJob(jobId, button) {
  setBusy(button, true, "生成中...");
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(jobId)}/generate-resume`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    $("#versionPreview").textContent = result.resume.content_md || "";
    await loadJobs();
    await loadVersions();
    showNotice(`已生成 ${result.resume.company} - ${result.resume.title} 的定制简历`);
    switchView("versions");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function loadVersions() {
  const data = await api("/api/resume-versions");
  state.versions = data.versions || [];
  renderVersions();
}

function renderVersions() {
  const container = $("#versionList");
  if (!state.versions.length) {
    container.className = "version-list empty";
    container.textContent = "暂无简历版本";
    return;
  }
  container.className = "version-list";
  container.innerHTML = state.versions
    .map((version) => `
      <button class="version-card ${state.selectedVersionId === version.id ? "active" : ""}" type="button" data-version-id="${version.id}">
        <span class="version-title">
          <span>版本 #${version.id}</span>
          <span class="chip">${escapeHtml(version.status || "draft")}</span>
        </span>
        <span class="version-meta">
          <span class="chip">${escapeHtml(version.created_at || "")}</span>
          <span class="chip">${escapeHtml(version.job_id || "")}</span>
        </span>
        <span class="muted">${escapeHtml(version.file_path || "stored in DB")}</span>
      </button>
    `)
    .join("");
}

async function selectVersion(versionId) {
  state.selectedVersionId = Number(versionId);
  renderVersions();
  const data = await api(`/api/resume-versions/${versionId}`);
  $("#versionPreview").textContent = data.version.content_md || "该版本没有 Markdown 内容";
}

async function sendChat(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const input = form.message;
  const text = input.value.trim();
  if (!text) return;

  appendMessage("user", text);
  input.value = "";
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: text }),
    });
    appendMessage("agent", result.reply);
    if (result.action === "suggest_search" && result.data.keywords) {
      $("#searchForm").keywords.value = result.data.keywords;
    }
  } catch (error) {
    appendMessage("agent", error.message);
  }
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  $("#chatLog").appendChild(node);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
}

function renderSettings() {
  const health = state.health || {};
  const config = state.config || {};
  $("#settingDb").textContent = config.db_path || health.db_path || "-";
  $("#settingBoss").textContent = health.boss_login_exists ? "已找到登录态" : "未找到登录态";
  $("#settingOpenai").textContent =
    (config.model_provider || health.model_provider) === "ollama"
      ? `Ollama · ${config.ollama_model || "未填写模型"}`
      : health.openai_configured
        ? `OpenAI-compatible · ${config.openai_model || ""}`
        : "OpenAI-compatible 未配置";
  $("#settingFeishu").textContent = health.feishu_configured ? "已配置" : "未配置";
  $("#settingResume").textContent = health.resume_exists ? "已创建" : "未创建";
}

function parseList(value) {
  return String(value || "")
    .split(/[,，、\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function arrayText(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function parseJsonField(value, label) {
  const trimmed = value.trim();
  if (!trimmed) return [];
  try {
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch (error) {
    throw new Error(`${label} 格式错误: ${error.message}`);
  }
}

function listHtml(items, emptyText) {
  if (!items.length) return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function bindEvents() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  $$("[data-view-jump]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.viewJump));
  });
  $("#refreshBtn").addEventListener("click", refreshAll);
  $("#profileForm").addEventListener("submit", saveProfile);
  $("#templateForm").addEventListener("submit", generateTemplate);
  $("#searchForm").addEventListener("submit", runSearch);
  $("#configForm").addEventListener("submit", saveConfig);
  $("#chatForm").addEventListener("submit", sendChat);
  $("#reloadJobsBtn").addEventListener("click", loadJobs);
  $("#reloadVersionsBtn").addEventListener("click", loadVersions);

  $("#jobList").addEventListener("click", (event) => {
    const card = event.target.closest("[data-job-id]");
    if (card) selectJob(card.dataset.jobId);
  });
  $("#latestJobs").addEventListener("click", (event) => {
    const card = event.target.closest("[data-job-id]");
    if (card) {
      switchView("matches");
      selectJob(card.dataset.jobId);
    }
  });
  $("#jobDetail").addEventListener("click", (event) => {
    const button = event.target.closest("#jobResumeBtn");
    if (button) generateForSelectedJob(button.dataset.jobId, button);
  });
  $("#versionList").addEventListener("click", (event) => {
    const card = event.target.closest("[data-version-id]");
    if (card) selectVersion(card.dataset.versionId);
  });
  $$(".prompt-chip").forEach((button) => {
    button.addEventListener("click", () => {
      $("#chatForm").message.value = button.textContent;
      $("#chatForm").requestSubmit();
    });
  });
}

async function refreshAll() {
  showNotice("");
  await checkHealth();
  await loadDashboard();
  if ($("#matches").classList.contains("active")) await loadJobs();
  if ($("#versions").classList.contains("active")) await loadVersions();
}

bindEvents();
refreshAll().catch((error) => showNotice(error.message, "error"));
