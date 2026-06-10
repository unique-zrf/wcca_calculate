const state = { data: null, models: [], view: "dashboard" };

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function refresh() {
  state.data = await api("/api/state");
  renderState();
}

function renderState() {
  const data = state.data;
  $("projectName").textContent = data.project_dir;
  $("resultStatus").textContent = data.summary.status || "-";
  $("releaseStatus").textContent = data.summary.release_status || "-";
  $("blockCount").textContent = data.summary.result_count ?? "-";
  $("minMargin").textContent = data.summary.min_margin == null ? "-" : `${data.summary.min_margin}%`;
  $("auditStatus").textContent = data.audit.status || "-";
  $("workflowState").textContent = data.workflow.state || "-";
  $("workflowJson").textContent = JSON.stringify(data.workflow, null, 2);

  $("blockRows").innerHTML = data.blocks.map(row => `
    <tr>
      <td>${escapeHtml(row.id || "")}</td>
      <td>${escapeHtml(row.type || "")}</td>
      <td>${escapeHtml(row.model || "")}</td>
      <td>${format(row.worst_min)}</td>
      <td>${format(row.worst_max)}</td>
      <td>${format(row.margin_min)} / ${format(row.margin_max)}</td>
      <td><span class="pill ${row.pass_fail === "fail" ? "bad" : ""}">${escapeHtml(row.pass_fail || "-")}</span></td>
    </tr>
  `).join("");

  $("riskList").innerHTML = (data.risks || []).map(risk =>
    `<li>${escapeHtml(risk.circuit_block_id || "")}: ${escapeHtml(risk.risk_type || "")} ${escapeHtml(risk.description || "")}</li>`
  ).join("") || "<li>No risk items reported.</li>";

  $("artifactList").innerHTML = (data.artifacts || []).map(item =>
    `<li><button class="linkBtn" data-file="${escapeAttr(item.path)}">${escapeHtml(item.label)}</button></li>`
  ).join("");

  const agentRoles = ["planner", "parameter_extractor", "circuit_analysis", "calculation_reviewer", "report_writer", "compliance_reviewer"];
  $("agentCards").innerHTML = agentRoles.map(role => `
    <div class="agentCard">
      <strong>${role.replaceAll("_", " ")}</strong>
      <span>${data.files.agent_run ? "artifact available" : "not generated"}</span>
      <button data-file="work/agents/${role}.md">Open</button>
    </div>
  `).join("");

  document.querySelectorAll("[data-file]").forEach(btn => {
    btn.addEventListener("click", () => openArtifact(btn.dataset.file));
  });
}

async function loadModels() {
  const data = await api("/api/models");
  state.models = data.models;
  $("modelRows").innerHTML = data.models.map(model => `
    <tr>
      <td>${escapeHtml(model.model_id)}</td>
      <td>${escapeHtml(model.version)}</td>
      <td>${escapeHtml(model.status)}</td>
      <td>${escapeHtml((model.circuit_types || []).join(", "))}</td>
      <td>${escapeHtml(model.kb_card_id)}</td>
    </tr>
  `).join("");
}

async function searchKnowledge() {
  const q = encodeURIComponent($("knowledgeQuery").value);
  const data = await api(`/api/knowledge/search?q=${q}`);
  $("knowledgeResults").innerHTML = data.results.map(item => `
    <div class="knowledgeItem">
      <strong>${escapeHtml(item.id)} · ${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.summary || "")}</p>
      <p>${escapeHtml(item.path || "")}</p>
    </div>
  `).join("") || "<div class=\"knowledgeItem\">No matches.</div>";
}

async function runAction(action, body = {}) {
  showToast(`Running ${action}...`);
  const data = await api(`/api/actions/${action}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (data.state) state.data = data.state;
  renderState();
  showToast(`${action} completed`);
  return data;
}

async function openArtifact(path) {
  const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
  let content = data.content;
  if (typeof content !== "string") content = JSON.stringify(content, null, 2);
  $("artifactPreview").textContent = content;
  setView("artifacts");
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach(el => el.classList.toggle("active", el.id === view));
  document.querySelectorAll("nav button").forEach(btn => btn.classList.toggle("active", btn.dataset.view === view));
  $("pageTitle").textContent = document.querySelector(`nav button[data-view="${view}"]`).textContent;
}

async function runPipeline() {
  const steps = ["ingest", "extract", "normalize", "calculate", "validate", "report-export", "document-build", "agent-run", "review-checklist", "integration-dispatch", "package", "audit"];
  for (const step of steps) {
    await runAction(step);
  }
}

function format(value) {
  if (value == null) return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  return escapeHtml(String(value));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.style.display = "block";
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.style.display = "none"; }, 3000);
}

document.querySelectorAll("nav button").forEach(btn => {
  btn.addEventListener("click", async () => {
    setView(btn.dataset.view);
    if (btn.dataset.view === "models") await loadModels();
  });
});

document.querySelectorAll("[data-action]").forEach(btn => {
  btn.addEventListener("click", () => runAction(btn.dataset.action).catch(err => showToast(err.message)));
});

document.querySelectorAll("[data-workflow]").forEach(btn => {
  btn.addEventListener("click", () => runAction("review-flow", { action: btn.dataset.workflow, reviewer: "web_user" }).catch(err => showToast(err.message)));
});

$("refreshBtn").addEventListener("click", () => refresh().catch(err => showToast(err.message)));
$("runPipelineBtn").addEventListener("click", () => runPipeline().catch(err => showToast(err.message)));
$("knowledgeBtn").addEventListener("click", () => searchKnowledge().catch(err => showToast(err.message)));

refresh().then(loadModels).then(searchKnowledge).catch(err => showToast(err.message));
