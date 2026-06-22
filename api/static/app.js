const state = {
  health: null,
  config: null,
  dashboard: null,
  jobs: [],
  versions: [],
  selectedJobId: null,
  selectedVersionId: null,
  commands: [],
  activeTaskId: null,
  taskPollTimer: null,
  bossLoginPending: false,
  apiToken: localStorage.getItem("jobmatch_api_token") || "",
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

const taskStages = [
  ["queued", "排队"],
  ["waiting", "等待"],
  ["starting", "启动"],
  ["planning", "解析"],
  ["login", "登录"],
  ["scraping", "Boss"],
  ["retrieving", "证据"],
  ["matching", "匹配"],
  ["optimizing", "简历"],
  ["reviewing", "复核"],
  ["notifying", "通知"],
  ["recording", "保存"],
  ["completed", "完成"],
];

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

function emptyState(title, detail = "") {
  return `
    <div>
      <strong>${escapeHtml(title)}</strong>
      ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
    </div>
  `;
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.apiToken) {
    headers.Authorization = `Bearer ${state.apiToken}`;
  }
  const response = await fetch(path, {
    headers,
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    const token = window.prompt("需要 API Token（WEBUI_API_TOKEN）:");
    if (token) {
      state.apiToken = token.trim();
      localStorage.setItem("jobmatch_api_token", state.apiToken);
      return api(path, options);
    }
  }
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
  if (view === "settings") {
    loadConfig();
    loadKnowledgeStatus();
  }
  if (view === "search") renderBossLoginStatus();
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    state.health = data;
    const online = data.status === "ok" || data.ok;
    $("#healthDot").className = online ? "dot online" : "dot offline";
    $("#healthText").textContent = data.status || (online ? "online" : "degraded");
    $("#healthMeta").textContent = online ? "后端已连接" : "服务异常";
    renderBossLoginStatus();
  } catch (error) {
    $("#healthDot").className = "dot offline";
    $("#healthText").textContent = "offline";
    $("#healthMeta").textContent = error.message;
    renderBossLoginStatus({ offline: true });
  }
  renderSettings();
}

function isBossLoggedIn() {
  return Boolean(state.health?.boss_login_exists);
}

function renderBossLoginStatus(options = {}) {
  const dot = $("#bossLoginDot");
  const text = $("#bossLoginText");
  const meta = $("#bossLoginMeta");
  const banner = $("#bossSearchBanner");
  if (!dot || !text || !meta) return;

  if (options.offline) {
    dot.className = "dot offline";
    text.textContent = "Boss 状态未知";
    meta.textContent = "后端未连接";
    if (banner) banner.classList.add("hidden");
    return;
  }

  if (state.activeTaskId && state.bossLoginPending) {
    dot.className = "dot pending";
    text.textContent = "等待 Boss 登录";
    meta.textContent = "请在 Chrome 或下方二维码扫码";
    if (banner) {
      banner.className = "boss-search-banner pending";
      banner.textContent = "正在等待 Boss 扫码登录。请在弹出的 Chrome 窗口完成登录；若出现安全验证，手动点一下后任务会自动重试。";
      banner.classList.remove("hidden");
    }
    return;
  }

  if (isBossLoggedIn()) {
    dot.className = "dot online";
    text.textContent = "Boss 已登录";
    meta.textContent = "可直接发起搜索";
    if (banner) {
      banner.className = "boss-search-banner ok";
      banner.textContent = "Boss 登录态有效。搜索会在 Chrome 中可视化打开岗位列表，不会自动投递或批量私信。";
      banner.classList.remove("hidden");
    }
    return;
  }

  dot.className = "dot warn";
  text.textContent = "Boss 未登录";
  meta.textContent = "搜索时将打开 Chrome 扫码";
  if (banner) {
    banner.className = "boss-search-banner";
    banner.textContent = "尚未检测到 Boss 登录。发起搜索后会弹出 Chrome 登录页，也可用终端运行 python scripts/login_boss.py 预先登录。";
    banner.classList.remove("hidden");
  }
}

function confirmBossSearch() {
  if (isBossLoggedIn()) return true;
  return window.confirm(
    "尚未检测到 Boss 登录态。\n\n" +
    "继续后将打开 Chrome 登录页，请用 Boss 直聘 App 扫码。\n" +
    "若出现安全验证，在浏览器里手动完成即可，任务会自动重试。\n\n" +
    "本工具只做搜索与匹配展示，不会自动投递或批量私信。是否继续？"
  );
}

async function loadKnowledgeStatus() {
  try {
    const data = await api("/api/knowledge/status");
    $("#settingKnowledgeSources").textContent = String(data.indexed_sources ?? "-");
    const ingest = data.latest_ingest;
    $("#settingKnowledgeIngest").textContent = ingest
      ? `${ingest.chunks} chunks · ${ingest.ingested_at}`
      : "尚未入库";
  } catch (error) {
    $("#settingKnowledgeSources").textContent = "-";
    $("#settingKnowledgeIngest").textContent = error.message;
  }
}

async function ingestKnowledge() {
  const button = $("#ingestKnowledgeBtn");
  setBusy(button, true, "入库中...");
  try {
    const result = await api("/api/knowledge/ingest", { method: "POST" });
    showNotice(result.message || "知识库索引已重建");
    await loadKnowledgeStatus();
    await checkHealth();
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function loadCommands() {
  try {
    const data = await api("/api/commands");
    state.commands = data.commands || [];
    renderCommandHints();
  } catch (error) {
    state.commands = [];
  }
}

function renderCommandHints() {
  const container = $("#commandHints");
  if (!container || !state.commands.length) return;
  container.innerHTML = state.commands
    .slice(0, 6)
    .map((command) => `
      <button class="prompt-chip" type="button" data-command="${escapeAttr(command.name)}">
        <strong>${escapeHtml(command.name)}</strong>
        <span>${escapeHtml(command.usage || command.name)}</span>
      </button>
    `)
    .join("");
}

async function loadConfig() {
  try {
    const config = await api("/api/config");
    state.config = config;
    await renderModelOptions(config);
    renderConfigForm(config);
    renderSettings();
  } catch (error) {
    showNotice(error.message, "error");
  }
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

async function renderModelOptions(config) {
  renderStaticModelOptions(config);
  if ((config.model_provider || "openai") !== "ollama") return;

  try {
    const params = new URLSearchParams({
      provider: "ollama",
      base_url: config.ollama_base_url || "",
    });
    const data = await api(`/api/models?${params.toString()}`);
    setSelectOptions("ollama_model", data.chat_models || [], config.ollama_model, [
      "qwen2.5-coder:7b",
      "qwen2.5:7b",
      "llama3.1:8b",
    ]);
    setSelectOptions("ollama_embedding_model", data.embedding_models || [], config.ollama_embedding_model, [
      "nomic-embed-text",
      "mxbai-embed-large",
    ]);
    if (data.warning) showNotice(data.warning);
  } catch (error) {
    showNotice(error.message, "error");
  }
}

function renderStaticModelOptions(config) {
  setSelectOptions("openai_model", [
    "gpt-4o-mini",
    "gpt-4o",
    "deepseek-chat",
    "deepseek-reasoner",
    "qwen-plus",
    "qwen-turbo",
  ], config.openai_model);
  setSelectOptions("openai_embedding_model", [
    "text-embedding-3-small",
    "text-embedding-3-large",
  ], config.openai_embedding_model);
  setSelectOptions("ollama_model", [], config.ollama_model, [
    "qwen2.5-coder:7b",
    "qwen2.5:7b",
    "llama3.1:8b",
  ]);
  setSelectOptions("ollama_embedding_model", [], config.ollama_embedding_model, [
    "nomic-embed-text",
    "mxbai-embed-large",
  ]);
}

function setSelectOptions(name, primaryOptions, selectedValue, fallbackOptions = []) {
  const select = $(`#configForm [name="${name}"]`);
  if (!select) return;
  const values = [...new Set([...(primaryOptions || []), selectedValue, ...(fallbackOptions || [])].filter(Boolean))];
  select.innerHTML = values
    .map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`)
    .join("");
  select.value = selectedValue || values[0] || "";
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
  try {
    const data = await api("/api/dashboard");
    state.dashboard = data;
    $("#metricJobs").textContent = data.metrics.jobs;
    $("#metricMatches").textContent = data.metrics.matches;
    $("#metricResumes").textContent = data.metrics.resumes;
    $("#metricPlans").textContent = data.metrics.plans;
    renderJobList($("#latestJobs"), data.latest_jobs || [], { compact: true });
  } catch (error) {
    renderJobList($("#latestJobs"), [], { compact: true });
    showNotice(error.message, "error");
  }
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

async function importResume(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#importResumeBtn");
  setBusy(button, true, "生成中...");
  try {
    const result = await api("/api/import-resume", {
      method: "POST",
      body: JSON.stringify({
        content: form.content.value,
        target_roles: form.target_roles.value,
        cities: form.cities.value,
        source_label: "web_import",
      }),
    });
    await loadProfile();
    await checkHealth();
    const extracted = result.extracted || {};
    showNotice(`${result.message} 技能 ${extracted.skills || 0} 项，项目 ${extracted.projects || 0} 个，经历 ${extracted.experience || 0} 段。`);
    form.content.value = "";
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
  if (!confirmBossSearch()) return;

  const form = event.currentTarget;
  const button = $("#searchBtn");
  const output = $("#searchResult");
  setBusy(button, true, "启动中...");
  output.textContent = "正在创建后台搜索任务。";
  try {
    const task = await api("/api/jobs/search/tasks", {
      method: "POST",
      body: JSON.stringify({
        keywords: form.keywords.value,
        city: form.city.value || "全国",
        threshold: Number(form.threshold.value || 75),
      }),
    });
    showNotice(task.message || "搜索任务已启动");
    startTaskPolling(task.task_id);
  } catch (error) {
    output.textContent = error.message;
    showNotice(error.message, "error");
    setBusy(button, false);
    return;
  } finally {
    if (!state.activeTaskId) setBusy(button, false);
  }
}

function startTaskPolling(taskId) {
  state.activeTaskId = taskId;
  state.bossLoginPending = !isBossLoggedIn();
  renderBossLoginStatus();
  if (state.taskPollTimer) clearTimeout(state.taskPollTimer);
  pollTask(taskId);
}

async function pollTask(taskId) {
  try {
    const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    if (task.stage === "login") {
      state.bossLoginPending = true;
    } else if (task.status === "completed") {
      state.bossLoginPending = false;
    }
    renderBossLoginStatus();
    renderTask(task);
    if (task.status === "completed") {
      await finishTask(task);
      return;
    }
    if (task.status === "failed") {
      failTask(task);
      return;
    }
    state.taskPollTimer = setTimeout(() => pollTask(taskId), 1200);
  } catch (error) {
    showNotice(error.message, "error");
    state.taskPollTimer = setTimeout(() => pollTask(taskId), 2500);
  }
}

async function finishTask(task) {
  const result = task.result || {};
  state.activeTaskId = null;
  state.bossLoginPending = false;
  if (state.taskPollTimer) clearTimeout(state.taskPollTimer);
  state.taskPollTimer = null;
  state.jobs = result.jobs || [];
  renderTask(task);
  renderJobList($("#jobList"), state.jobs);
  await loadDashboard();
  await loadJobs();
  await checkHealth();
  setBusy($("#searchBtn"), false);
  appendMessage("agent", `${result.message || "搜索完成"} 抓取 ${result.jobs_scraped || 0} 个岗位，匹配 ${result.matches_scored || 0} 个。`);
  switchView("matches");
}

function failTask(task) {
  state.activeTaskId = null;
  state.bossLoginPending = false;
  renderBossLoginStatus();
  if (state.taskPollTimer) clearTimeout(state.taskPollTimer);
  state.taskPollTimer = null;
  renderTask(task);
  setBusy($("#searchBtn"), false);
  showNotice(task.message || "搜索任务失败", "error");
  appendMessage("agent", task.message || "搜索任务失败");
}

function renderTask(task) {
  const html = taskHtml(task);
  const searchResult = $("#searchResult");
  const activePanel = $("#activeTaskPanel");
  if (searchResult) searchResult.innerHTML = html;
  if (activePanel) {
    activePanel.innerHTML = html;
    activePanel.classList.remove("hidden");
    if (task.status === "completed" || task.status === "failed") {
      setTimeout(() => activePanel.classList.add("hidden"), 8000);
    }
  }
}

function taskHtml(task) {
  const events = task.events || [];
  const result = task.result || {};
  const statusText = {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
  }[task.status] || task.status;
  const seenStages = new Set(events.map((event) => event.stage));
  if (task.stage) seenStages.add(task.stage);
  const screenshotSrc = task.login_screenshot_url
    ? `${task.login_screenshot_url}${task.login_screenshot_url.includes("?") ? "&" : "?"}t=${Date.now()}`
    : task.login_screenshot
      ? `data:image/png;base64,${task.login_screenshot}`
      : "";
  const securityHint = (task.message || "").includes("安全") || (task.message || "").includes("security")
    ? `<div class="task-hint">出现 Boss 安全验证时，请在 Chrome 窗口手动完成，完成后任务会自动重试。</div>`
    : task.stage === "login"
      ? `<div class="task-hint">请在弹出的 Chrome 窗口或下方二维码扫码登录。登录成功后无需再次提交搜索。</div>`
      : "";
  return `
    <div class="task-card" data-status="${escapeAttr(task.status)}">
      <div class="task-head">
        <div>
          <strong>${escapeHtml(statusText)} · ${escapeHtml(task.message || "")}</strong>
          <span>${escapeHtml((task.request?.city || "全国"))} · ${escapeHtml((task.request?.keywords || []).join(", "))}</span>
        </div>
        <span class="task-percent">${Number(task.progress || 0)}%</span>
      </div>
      <div class="progress-track"><span style="width:${Number(task.progress || 0)}%"></span></div>
      <div class="stage-rail">
        ${taskStages.map(([stage, label]) => `
          <span class="${stage === task.stage ? "active" : seenStages.has(stage) ? "done" : ""}">
            ${escapeHtml(label)}
          </span>
        `).join("")}
      </div>
      ${screenshotSrc ? `
        <div class="login-qr">
          <img src="${escapeAttr(screenshotSrc)}" alt="Boss 登录二维码截图" />
          <div>
            <strong>扫码登录 Boss</strong>
            <p>请用 Boss 直聘 App 扫码。登录成功后，Agent 会自动继续搜索，不需要再次提交。</p>
            <a class="plain-link" href="${escapeAttr(screenshotSrc)}" target="_blank" rel="noreferrer">打开登录截图</a>
          </div>
        </div>
      ` : ""}
      ${securityHint}
      <div class="task-events">
        ${events.map((event) => `
          <div class="task-event ${event.stage === task.stage ? "active" : ""}">
            <span>${escapeHtml(String(event.progress))}%</span>
            <p>${escapeHtml(event.message)}</p>
          </div>
        `).join("")}
      </div>
      ${task.status === "completed" ? `
        <div class="task-summary">
          <span>岗位 ${Number(result.jobs_scraped || 0)}</span>
          <span>匹配 ${Number(result.matches_scored || 0)}</span>
          <span>简历 ${Number(result.resumes_generated || 0)}</span>
          <span>通知 ${Number(result.notified || 0)}</span>
        </div>
      ` : ""}
    </div>
  `;
}

async function loadJobs() {
  try {
    const data = await api("/api/jobs");
    state.jobs = data.jobs || [];
    renderJobList($("#jobList"), state.jobs);
  } catch (error) {
    renderJobList($("#jobList"), []);
    showNotice(error.message, "error");
  }
}

function renderJobList(container, jobs, options = {}) {
  if (!container) return;
  if (!jobs.length) {
    container.className = "job-list empty";
    container.innerHTML = emptyState(
      "暂无岗位记录",
      options.compact ? "完成一次搜索后，最新岗位会出现在这里。" : "去岗位搜索页启动一次搜索，Agent 会抓取并评分。"
    );
    return;
  }

  container.className = "job-list";
  container.innerHTML = jobs
    .map((job) => {
      const match = job.match || {};
      const score = Number(match.score || 0);
      const scoreClass = score >= 80 ? "" : score >= 60 ? "mid" : "low";
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
            <span class="score ${scoreClass}">${score}</span>
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
  try {
    const data = await api("/api/resume-versions");
    state.versions = data.versions || [];
    renderVersions();
  } catch (error) {
    state.versions = [];
    renderVersions();
    showNotice(error.message, "error");
  }
}

function renderVersions() {
  const container = $("#versionList");
  if (!state.versions.length) {
    container.className = "version-list empty";
    container.innerHTML = emptyState("暂无简历版本", "在匹配详情中生成定制简历，或从模板生成器创建第一版。");
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
  const slashCommand = text.trimStart().split(/\s+/, 1)[0].toLowerCase();
  if ((slashCommand === "/search" || slashCommand.startsWith("/search")) && !confirmBossSearch()) {
    appendMessage("agent", "已取消搜索。可先运行 python scripts/login_boss.py 完成 Boss 登录，或确认后在 Chrome 中扫码。");
    hideCommandMenu();
    return;
  }
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: text }),
    });
    appendMessage("agent", result.reply);
    await handleChatAction(result);
  } catch (error) {
    appendMessage("agent", error.message);
  } finally {
    hideCommandMenu();
  }
}

async function handleChatAction(result) {
  const data = result.data || {};
  if ((result.action === "suggest_search" || result.action === "search_complete" || result.action === "search_started") && data.keywords) {
    $("#searchForm").keywords.value = data.keywords;
    if ($("#searchForm").city) $("#searchForm").city.value = data.city || "全国";
    if ($("#searchForm").threshold) $("#searchForm").threshold.value = data.threshold || 75;
  }
  if (result.action === "search_started" && data.task_id) {
    startTaskPolling(data.task_id);
  }
  if (result.action === "search_complete") {
    state.jobs = data.jobs || [];
    renderJobList($("#jobList"), state.jobs);
    await loadDashboard();
    switchView("matches");
  }
  if (result.action === "dashboard") {
    await loadDashboard();
    switchView("dashboard");
  }
  if (result.action === "navigate" && data.view) {
    switchView(data.view);
  }
  if (result.action === "resume_advice" && data.target_role) {
    switchView("profile");
    const template = $("#templateForm");
    if (template?.target_role) template.target_role.value = data.target_role;
  }
}

function updateCommandMenu() {
  const input = $("#chatForm").message;
  const menu = $("#commandMenu");
  if (!input || !menu) return;
  const value = input.value;
  updateCommandParams(value);
  if (!value.startsWith("/")) {
    hideCommandMenu();
    return;
  }

  const needle = value.slice(1).split(/\s+/, 1)[0].toLowerCase();
  const matches = state.commands.filter((command) =>
    command.name.slice(1).toLowerCase().startsWith(needle)
  );
  if (!matches.length) {
    hideCommandMenu();
    return;
  }

  menu.innerHTML = matches
    .map((command) => `
      <button class="command-option" type="button" data-command="${escapeAttr(command.name)}">
        <span>
          <strong>${escapeHtml(command.usage || command.name)}</strong>
          <small>${escapeHtml(command.description)}</small>
        </span>
        <kbd>${escapeHtml(command.label)}</kbd>
      </button>
    `)
    .join("");
  menu.classList.remove("hidden");
}

function hideCommandMenu() {
  const menu = $("#commandMenu");
  if (menu) menu.classList.add("hidden");
}

function updateCommandParams(value = "") {
  const params = $("#commandParams");
  if (!params) return;
  const commandName = value.trimStart().split(/\s+/, 1)[0];
  const command = state.commands.find((item) => item.name === commandName);
  if (!command || !command.params) {
    params.classList.add("hidden");
    params.textContent = "";
    return;
  }
  params.innerHTML = `
    <span>参数</span>
    <code>${escapeHtml(command.params)}</code>
    ${command.example ? `<small>例：${escapeHtml(command.example)}</small>` : ""}
  `;
  params.classList.remove("hidden");
}

function applyCommand(commandName) {
  const input = $("#chatForm").message;
  const command = state.commands.find((item) => item.name === commandName);
  input.value = `${command?.name || commandName} `;
  input.focus();
  updateCommandParams(input.value);
  hideCommandMenu();
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
  if (!$("#settingDb")) return;
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
  if (health.knowledge_ingest) {
    $("#settingKnowledgeIngest").textContent = `${health.knowledge_ingest.chunks} chunks · ${health.knowledge_ingest.ingested_at}`;
  }
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
  $("#refreshBtn")?.addEventListener("click", refreshAll);
  $("#profileForm")?.addEventListener("submit", saveProfile);
  $("#importResumeForm")?.addEventListener("submit", importResume);
  $("#templateForm")?.addEventListener("submit", generateTemplate);
  $("#searchForm")?.addEventListener("submit", runSearch);
  $("#configForm")?.addEventListener("submit", saveConfig);
  $("#ingestKnowledgeBtn")?.addEventListener("click", ingestKnowledge);
  $("#refreshModelsBtn")?.addEventListener("click", async () => {
    const form = $("#configForm");
    const config = {
      ...(state.config || {}),
      model_provider: form.model_provider.value,
      ollama_base_url: form.ollama_base_url.value,
      ollama_model: form.ollama_model.value,
      ollama_embedding_model: form.ollama_embedding_model.value,
      openai_model: form.openai_model.value,
      openai_embedding_model: form.openai_embedding_model.value,
    };
    await renderModelOptions(config);
    showNotice("模型选项已刷新");
  });
  $("#configForm")?.model_provider?.addEventListener("change", async () => {
    const form = $("#configForm");
    await renderModelOptions({ ...(state.config || {}), model_provider: form.model_provider.value, ollama_base_url: form.ollama_base_url.value });
  });
  $("#configForm")?.ollama_base_url?.addEventListener("change", async () => {
    const form = $("#configForm");
    await renderModelOptions({ ...(state.config || {}), model_provider: form.model_provider.value, ollama_base_url: form.ollama_base_url.value });
  });
  $("#chatForm")?.addEventListener("submit", sendChat);
  $("#chatForm")?.message?.addEventListener("input", updateCommandMenu);
  $("#chatForm")?.message?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideCommandMenu();
  });
  $("#commandMenu")?.addEventListener("click", (event) => {
    const option = event.target.closest("[data-command]");
    if (option) applyCommand(option.dataset.command);
  });
  $("#reloadJobsBtn")?.addEventListener("click", loadJobs);
  $("#reloadVersionsBtn")?.addEventListener("click", loadVersions);

  $("#jobList")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-job-id]");
    if (card) selectJob(card.dataset.jobId);
  });
  $("#latestJobs")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-job-id]");
    if (card) {
      switchView("matches");
      selectJob(card.dataset.jobId);
    }
  });
  $("#jobDetail")?.addEventListener("click", (event) => {
    const button = event.target.closest("#jobResumeBtn");
    if (button) generateForSelectedJob(button.dataset.jobId, button);
  });
  $("#versionList")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-version-id]");
    if (card) selectVersion(card.dataset.versionId);
  });
  $("#commandHints")?.addEventListener("click", (event) => {
    const button = event.target.closest(".prompt-chip");
    if (!button) return;
    applyCommand(button.dataset.command || button.textContent.trim().split(/\s+/, 1)[0]);
  });
}

async function refreshAll() {
  showNotice("");
  await loadCommands();
  await checkHealth();
  await loadDashboard();
  if ($("#matches").classList.contains("active")) await loadJobs();
  if ($("#versions").classList.contains("active")) await loadVersions();
}

bindEvents();
refreshAll().catch((error) => showNotice(error.message, "error"));
