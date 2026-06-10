const STAGES = [
  "director",
  "image_generation",
  "vision_critique",
  "video_generation",
  "tts_generation",
  "stitching",
];

const POLL_INTERVAL_MS = 2000;

let renderMode = "prototype";
let currentJobId = null;
let pollTimer = null;

const ideaInput = document.getElementById("idea");
const generateBtn = document.getElementById("generate-btn");
const generateText = generateBtn.querySelector(".btn-generate__text");
const generateSpinner = generateBtn.querySelector(".btn-generate__spinner");
const inputSection = document.getElementById("input-section");
const pipelineSection = document.getElementById("pipeline-section");
const resultSection = document.getElementById("result-section");
const ideaEcho = document.getElementById("idea-echo");
const statusBadge = document.getElementById("status-badge");
const errorBanner = document.getElementById("error-banner");
const steps = document.querySelectorAll(".step");
const resultVideo = document.getElementById("result-video");
const downloadLink = document.getElementById("download-link");
const creditsBtn = document.getElementById("credits-btn");
const creditsPanel = document.getElementById("credits-panel");
const creditsBody = document.getElementById("credits-body");
const newRunBtn = document.getElementById("new-run-btn");

document.querySelectorAll(".toggle-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderMode = btn.dataset.mode;
  });
});

generateBtn.addEventListener("click", startGeneration);
newRunBtn.addEventListener("click", resetUi);
creditsBtn.addEventListener("click", toggleCredits);

async function startGeneration() {
  const idea = ideaInput.value.trim();
  if (!idea) {
    ideaInput.focus();
    return;
  }

  setGenerating(true);
  resetPipelineUi();
  ideaEcho.textContent = `"${idea}"`;
  pipelineSection.hidden = false;
  resultSection.hidden = true;
  errorBanner.hidden = true;

  try {
    const res = await fetch("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea, render_mode: renderMode }),
    });

    if (!res.ok) {
      throw new Error(await res.text());
    }

    const data = await res.json();
    currentJobId = data.job_id;
    updateStatusBadge("running", "Running");
    startPolling();
  } catch (err) {
    showError(err.message || "Failed to start generation");
    setGenerating(false);
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollStatus();
  pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
}

async function pollStatus() {
  if (!currentJobId) return;

  try {
    const res = await fetch(`/status/${currentJobId}`);
    if (!res.ok) throw new Error("Status check failed");
    const data = await res.json();
    updatePipeline(data.stage, data.status);

    if (data.status === "done") {
      clearInterval(pollTimer);
      pollTimer = null;
      setGenerating(false);
      updateStatusBadge("done", "Complete");
      showResult();
    } else if (data.status === "failed") {
      clearInterval(pollTimer);
      pollTimer = null;
      setGenerating(false);
      updateStatusBadge("failed", "Failed");
      showError(data.error || "Pipeline failed");
    } else {
      updateStatusBadge("running", formatStage(data.stage));
    }
  } catch (err) {
    clearInterval(pollTimer);
    pollTimer = null;
    setGenerating(false);
    showError(err.message);
  }
}

function updatePipeline(stage, status) {
  const stageIndex = STAGES.indexOf(stage);

  steps.forEach((step) => {
    const stepStage = step.dataset.stage;
    const idx = STAGES.indexOf(stepStage);
    step.classList.remove("step--active", "step--done");

    if (status === "done" || stage === "complete") {
      step.classList.add("step--done");
    } else if (stage === "queued" && status === "running") {
      if (idx === 0) step.classList.add("step--active");
    } else if (stageIndex === -1) {
      // waiting to start
    } else if (idx < stageIndex) {
      step.classList.add("step--done");
    } else if (idx === stageIndex) {
      step.classList.add("step--active");
    }
  });
}

function updateStatusBadge(kind, label) {
  statusBadge.textContent = label;
  statusBadge.className = "status-badge";
  if (kind === "running") statusBadge.classList.add("status-badge--running");
  if (kind === "done") statusBadge.classList.add("status-badge--done");
  if (kind === "failed") statusBadge.classList.add("status-badge--failed");
}

function formatStage(stage) {
  const labels = {
    queued: "Queued",
    director: "Understanding idea",
    image_generation: "Generating visuals",
    vision_critique: "Refining motion",
    video_generation: "Rendering video",
    tts_generation: "Creating voiceover",
    stitching: "Stitching",
    complete: "Complete",
  };
  return labels[stage] || stage;
}

async function showResult() {
  resultSection.hidden = false;
  const videoUrl = `/download/${currentJobId}?t=${Date.now()}`;
  resultVideo.src = videoUrl;
  downloadLink.href = videoUrl;
  creditsPanel.hidden = true;
  resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function toggleCredits() {
  if (!currentJobId) return;

  if (!creditsPanel.hidden) {
    creditsPanel.hidden = true;
    return;
  }

  try {
    const res = await fetch(`/credits/${currentJobId}`);
    const entries = await res.json();
    creditsBody.innerHTML = "";

    if (!entries.length) {
      creditsBody.innerHTML = '<tr><td colspan="3">No credit data yet</td></tr>';
    } else {
      entries.forEach((entry) => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${escapeHtml(entry.model_id)}</td>
          <td>${escapeHtml(entry.call_type)}</td>
          <td>$${entry.cost_usd.toFixed(4)}</td>
        `;
        creditsBody.appendChild(row);
      });
    }

    creditsPanel.hidden = false;
  } catch {
    creditsBody.innerHTML = '<tr><td colspan="3">Could not load credits</td></tr>';
    creditsPanel.hidden = false;
  }
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function setGenerating(active) {
  generateBtn.disabled = active;
  generateText.hidden = active;
  generateSpinner.hidden = !active;
}

function resetPipelineUi() {
  steps.forEach((step) => step.classList.remove("step--active", "step--done"));
  updateStatusBadge("", "Queued");
}

function resetUi() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  currentJobId = null;
  setGenerating(false);
  resetPipelineUi();
  pipelineSection.hidden = true;
  resultSection.hidden = true;
  errorBanner.hidden = true;
  creditsPanel.hidden = true;
  resultVideo.removeAttribute("src");
  inputSection.scrollIntoView({ behavior: "smooth" });
}
