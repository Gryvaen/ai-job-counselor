const state = {
  apiToken: localStorage.getItem("jobmatch_api_token") || "",
  ollamaModel: localStorage.getItem("ollama_model") || "",
  modelCatalog: null,
};

const STEPS = ["job_analyzer", "skill_gap_analyzer", "learning_planner", "project_recommender"];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function showNotice(msg, type = "info") {
  const el = $("#notice");
  if (!msg) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = msg;
  el.dataset.type = type;
  el.classList.remove("hidden");
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.apiToken) headers.Authorization = `Bearer ${state.apiToken}`;
  const res = await fetch(path, { headers, ...options });
  const body = await res.json().catch(() => ({}));
  if (res.status === 401) {
    const token = window.prompt("需要 API Token（WEBUI_API_TOKEN）:");
    if (token) {
      state.apiToken = token.trim();
      localStorage.setItem("jobmatch_api_token", state.apiToken);
      return api(path, options);
    }
  }
  if (!res.ok) throw new Error(body.detail || "请求失败");
  return body;
}

function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = busy;
  const text = btn.querySelector(".btn-text");
  if (text) text.textContent = busy ? "分析中..." : "开始分析";
}

function setHealth(data) {
  const dot = $("#healthDot");
  const text = $("#healthText");
  const ok = data?.ok;
  dot.className = `dot ${ok ? (data.status === "ok" ? "online" : "degraded") : "offline"}`;
  const modelLabel = data?.default_model ? ` · ${data.default_model}` : "";
  text.textContent = ok ? `${data.status} · ollama${modelLabel}` : "offline";
}

function formatModelSize(bytes) {
  if (!bytes) return "";
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

function pickDefaultModel(catalog) {
  const names = catalog.models.map((m) => m.name);
  if (state.ollamaModel && names.includes(state.ollamaModel)) {
    return state.ollamaModel;
  }
  if (catalog.default && names.includes(catalog.default)) {
    return catalog.default;
  }
  return names[0] || "";
}

function renderModelSelect(catalog) {
  const field = $("#modelField");
  const select = $("#modelSelect");
  const hint = $("#modelHint");

  field.classList.remove("hidden");
  select.innerHTML = "";

  if (!catalog.models.length) {
    select.innerHTML = '<option value="">未检测到模型</option>';
    hint.textContent = "请确认 ollama 容器已启动：docker compose ps";
    hint.classList.remove("hidden");
    return;
  }

  hint.classList.add("hidden");
  const selected = pickDefaultModel(catalog);
  catalog.models.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item.name;
    const size = formatModelSize(item.size);
    opt.textContent = size ? `${item.name} (${size})` : item.name;
    if (item.name === selected) opt.selected = true;
    select.appendChild(opt);
  });
}

async function loadModels() {
  try {
    const catalog = await api("/api/models");
    state.modelCatalog = catalog;
    renderModelSelect(catalog);
  } catch {
    $("#modelField").classList.add("hidden");
  }
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    setHealth(data);
  } catch {
    setHealth({ ok: false });
  }
}

function updateStepUI(completed) {
  STEPS.forEach((step, i) => {
    const sidebarEl = document.querySelector(`.step-item[data-step="${step}"]`);
    const pipelineEl = document.querySelector(`.pipeline-bar .step[data-step="${step}"]`);

    [sidebarEl, pipelineEl].forEach((el) => {
      if (!el) return;
      el.classList.remove("done", "active");
      if (completed.includes(step)) {
        el.classList.add("done");
      } else if (i === completed.length) {
        el.classList.add("active");
      }
    });
  });
}

function resetPipeline() {
  $("#pipeline").classList.remove("hidden");
  $("#results").classList.add("hidden");
  $("#inputSection").classList.add("hidden");
  updateStepUI([]);
}

function showInputSection() {
  $("#inputSection").classList.remove("hidden");
  $("#pipeline").classList.add("hidden");
  $("#results").classList.add("hidden");
  updateStepUI([]);
  showNotice("");
}

function animatePipeline(completed) {
  updateStepUI(completed);
}

function renderChips(items, cls = "chip") {
  if (!items?.length) return "<p class='muted'>无</p>";
  return `<div class="chips">${items.map((s) => `<span class="${cls}">${s}</span>`).join("")}</div>`;
}

function renderJob(job) {
  if (!job) return "<p class='muted'>暂无数据</p>";
  return `
    <p class="role-title">${job.title}</p>
    <p class="muted">${job.seniority} · ${job.summary || ""}</p>
    <h3>核心技能</h3>${renderChips(job.key_skills)}
    <h3>典型职责</h3>
    <ul>${(job.responsibilities || []).map((r) => `<li>${r}</li>`).join("")}</ul>
  `;
}

function renderGap(data) {
  return `
    <p>${data.gap_summary || ""}</p>
    <h3>已匹配</h3>${renderChips(data.matched_skills, "chip match")}
    <h3>待补充</h3>${renderChips(data.skills_missing, "chip gap")}
  `;
}

function renderPlan(items) {
  if (!items?.length) return "<p class='muted'>暂无计划</p>";
  return items
    .map(
      (item) => `
    <div class="plan-item">
      <div class="plan-head"><strong>${item.skill}</strong><span>${item.duration}</span></div>
      <ul>${(item.tasks || []).map((t) => `<li>${t}</li>`).join("")}</ul>
      ${item.resources?.length ? `<p class="muted">资源：${item.resources.join(" · ")}</p>` : ""}
    </div>`
    )
    .join("");
}

function renderProjects(items) {
  if (!items?.length) return "<p class='muted'>暂无推荐</p>";
  return items
    .map(
      (p) => `
    <div class="project-item">
      <div class="plan-head"><strong>${p.title}</strong><span>${p.difficulty}</span></div>
      <p>${p.description}</p>
      ${renderChips(p.skills, "chip")}
    </div>`
    )
    .join("");
}

function switchTab(tabName) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tabName));
  const panels = { job: "#panelJob", gap: "#panelGap", plan: "#panelPlan", projects: "#panelProjects" };
  Object.entries(panels).forEach(([key, sel]) => {
    $(sel).classList.toggle("active", key === tabName);
  });
}

function renderResults(data) {
  $("#jobContent").innerHTML = renderJob(data.job_analysis);
  $("#gapContent").innerHTML = renderGap(data);
  $("#planContent").innerHTML = renderPlan(data.learning_plan);
  $("#projectsContent").innerHTML = renderProjects(data.project_recommendations);
  $("#jsonOutput").textContent = JSON.stringify(data, null, 2);
  $("#results").classList.remove("hidden");
  switchTab("job");
  animatePipeline(data.steps_completed || STEPS);
}

async function runConsult(form) {
  const btn = $("#submitBtn");
  setBusy(btn, true);
  showNotice("");
  resetPipeline();

  const payload = {
    user_query: form.user_query.value.trim(),
    resume_text: form.resume_text.value.trim(),
    jd_text: form.jd_text.value.trim(),
  };

  const modelSelect = $("#modelSelect");
  if (modelSelect && !$("#modelField").classList.contains("hidden")) {
    const model = modelSelect.value.trim();
    if (model) {
      payload.model = model;
      state.ollamaModel = model;
      localStorage.setItem("ollama_model", model);
    }
  }

  try {
    STEPS.forEach((step, i) => {
      setTimeout(() => animatePipeline(STEPS.slice(0, i)), i * 200);
    });
    const data = await api("/api/consult", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderResults(data);
    showNotice("分析完成", "success");
  } catch (err) {
    showInputSection();
    showNotice(err.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

/* Sidebar toggle */
function openSidebar() {
  $("#sidebar").classList.add("open");
  $("#sidebarOverlay").classList.remove("hidden");
}

function closeSidebar() {
  $("#sidebar").classList.remove("open");
  $("#sidebarOverlay").classList.add("hidden");
}

$("#sidebarToggle")?.addEventListener("click", openSidebar);
$("#sidebarClose")?.addEventListener("click", closeSidebar);
$("#sidebarOverlay")?.addEventListener("click", closeSidebar);

/* Tab navigation */
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

/* Quick tips */
$$(".tip-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const input = $('input[name="user_query"]');
    if (input) {
      input.value = chip.dataset.query;
      input.focus();
    }
  });
});

/* New consult */
$("#newConsultBtn")?.addEventListener("click", showInputSection);

$("#consultForm").addEventListener("submit", (e) => {
  e.preventDefault();
  runConsult(e.target);
});

$("#modelSelect")?.addEventListener("change", (e) => {
  const model = e.target.value.trim();
  if (model) {
    state.ollamaModel = model;
    localStorage.setItem("ollama_model", model);
  }
});

checkHealth();
loadModels();
