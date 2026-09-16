(() => {
  const state = {
    jobId: null,
    jobTitle: "",
    candidates: [],
    files: [],
  };

  // ---------- Nav ----------
  const views = {
    intake: document.getElementById("view-intake"),
    results: document.getElementById("view-results"),
    history: document.getElementById("view-history"),
  };
  const navLinks = document.querySelectorAll(".nav-link[data-view]");

  function showView(name) {
    Object.entries(views).forEach(([key, el]) => { el.hidden = key !== name; });
    navLinks.forEach(btn => btn.classList.toggle("is-active", btn.dataset.view === name));
    if (name === "history") loadHistory();
  }

  navLinks.forEach(btn => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  document.getElementById("logout-btn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });

  // ---------- Job creation ----------
  const jobStatus = document.getElementById("job-status");
  const createJobBtn = document.getElementById("create-job-btn");
  const uploadPanel = document.getElementById("upload-panel");

  createJobBtn.addEventListener("click", async () => {
    const title = document.getElementById("job-title").value.trim();
    const description = document.getElementById("job-description").value.trim();
    const skillsRaw = document.getElementById("job-skills").value.trim();
    const required_skills = skillsRaw ? skillsRaw.split(",").map(s => s.trim()).filter(Boolean) : [];

    if (!title || !description) {
      setStatus(jobStatus, "Add a title and description before opening the role.", false);
      return;
    }

    createJobBtn.disabled = true;
    createJobBtn.textContent = "Opening…";
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, required_skills }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not open this role.");

      state.jobId = data.id;
      state.jobTitle = data.title;

      setStatus(jobStatus, "Role open — candidates can now find and apply to it. Optionally add resumes on the right too.", true);
      uploadPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      updateScreenButton();
    } catch (err) {
      setStatus(jobStatus, err.message, false);
    } finally {
      createJobBtn.disabled = false;
      createJobBtn.textContent = "Open this role";
    }
  });

  // ---------- File upload (recruiter-side bulk screening) ----------
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const fileListEl = document.getElementById("file-list");
  const screenBtn = document.getElementById("screen-btn");
  const uploadStatus = document.getElementById("upload-status");

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("is-dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", e => {
    e.preventDefault();
    dropzone.classList.remove("is-dragover");
    addFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener("change", () => addFiles(fileInput.files));

  function addFiles(fileListArg) {
    const allowed = [".pdf", ".docx", ".doc", ".txt"];
    Array.from(fileListArg).forEach(f => {
      const ext = "." + f.name.split(".").pop().toLowerCase();
      if (!allowed.includes(ext)) return;
      if (state.files.some(existing => existing.name === f.name && existing.size === f.size)) return;
      state.files.push(f);
    });
    renderFileList();
    updateScreenButton();
  }

  function renderFileList() {
    fileListEl.innerHTML = "";
    state.files.forEach((f, i) => {
      const li = document.createElement("li");
      const sizeKb = Math.round(f.size / 1024);
      li.innerHTML = `<span>${escapeHtml(f.name)} · ${sizeKb}kb</span><span class="remove-file" data-idx="${i}">remove</span>`;
      fileListEl.appendChild(li);
    });
    fileListEl.querySelectorAll(".remove-file").forEach(el => {
      el.addEventListener("click", () => {
        state.files.splice(Number(el.dataset.idx), 1);
        renderFileList();
        updateScreenButton();
      });
    });
  }

  function updateScreenButton() {
    screenBtn.disabled = !(state.jobId && state.files.length > 0);
  }

  screenBtn.addEventListener("click", async () => {
    if (!state.jobId || state.files.length === 0) return;
    const form = new FormData();
    state.files.forEach(f => form.append("resumes", f));

    showLoading(`Reading ${state.files.length} resume${state.files.length > 1 ? "s" : ""}…`);
    screenBtn.disabled = true;
    try {
      const res = await fetch(`/api/jobs/${state.jobId}/screen`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Screening failed.");

      state.candidates = data.candidates.map(c => ({ ...c, status: "applied" }));
      if (data.skipped && data.skipped.length) {
        setStatus(uploadStatus, `Skipped ${data.skipped.length} file(s) that couldn't be read: ${data.skipped.join(", ")}`, false);
      } else {
        setStatus(uploadStatus, "", true);
      }
      state.files = [];
      renderFileList();
      renderResults();
      showView("results");
    } catch (err) {
      setStatus(uploadStatus, err.message, false);
    } finally {
      hideLoading();
      updateScreenButton();
    }
  });

  // ---------- Results rendering ----------
  const resultsTray = document.getElementById("results-tray");
  const resultsTitle = document.getElementById("results-role-title");
  const resultsSummary = document.getElementById("results-summary");
  const sortSelect = document.getElementById("sort-select");
  const statusFilter = document.getElementById("status-filter");
  const searchInput = document.getElementById("search-input");

  sortSelect.addEventListener("change", renderResults);
  statusFilter.addEventListener("change", renderResults);
  searchInput.addEventListener("input", renderResults);

  function renderResults() {
    resultsTitle.textContent = state.jobTitle || "—";
    const query = searchInput.value.trim().toLowerCase();
    const statusWanted = statusFilter.value;

    let list = state.candidates.filter(c => {
      if (statusWanted !== "all" && c.status !== statusWanted) return false;
      if (!query) return true;
      const haystack = [c.name, ...(c.skills || [])].join(" ").toLowerCase();
      return haystack.includes(query);
    });

    const sortBy = sortSelect.value;
    list = [...list].sort((a, b) => {
      if (sortBy === "name") return a.name.localeCompare(b.name);
      return b.score - a.score;
    });

    resultsSummary.textContent = list.length
      ? `${list.length} of ${state.candidates.length} candidate${state.candidates.length > 1 ? "s" : ""} shown, sorted by ${sortBy === "name" ? "name" : "match score"}.`
      : "No candidates match that filter.";

    resultsTray.innerHTML = "";
    list.forEach(c => resultsTray.appendChild(buildDossier(c)));
  }

  function buildDossier(c) {
    const band = c.score >= 75 ? "band-high" : c.score >= 50 ? "band-mid" : "band-low";
    const el = document.createElement("article");
    el.className = "dossier";

    const matched = c.matched_skills || [];
    const missing = c.missing_skills || [];
    const otherSkills = (c.skills || []).filter(s => !matched.includes(s));

    const chipHtml = [
      ...matched.map(s => `<span class="chip matched">${escapeHtml(s)} ✓</span>`),
      ...missing.map(s => `<span class="chip missing">${escapeHtml(s)}</span>`),
      ...otherSkills.slice(0, 8).map(s => `<span class="chip plain">${escapeHtml(s)}</span>`),
    ].join("");

    el.innerHTML = `
      <div class="dossier-stamp ${band}">
        <div class="score-num">${Math.round(c.score)}</div>
        <div class="score-unit">match</div>
        <div class="rank-tag">#${c.rank ?? "—"}</div>
      </div>
      <div class="dossier-body">
        <div class="dossier-top">
          <h3 class="dossier-name">${escapeHtml(c.name)}</h3>
          <span class="dossier-contact">${escapeHtml(c.email)} ${c.phone && c.phone !== "Not found" ? "· " + escapeHtml(c.phone) : ""}</span>
        </div>
        <p class="dossier-meta">Content match ${c.similarity}%${c.skill_match_pct !== null && c.skill_match_pct !== undefined ? ` · Required skills covered ${c.skill_match_pct}%` : ""}
          <span class="status-badge status-${c.status}">${c.status}</span>
        </p>
        <div class="skill-row">${chipHtml || '<span class="chip plain">No listed skills detected</span>'}</div>
        <div class="dossier-actions">
          <a href="/api/resume/${state.jobId}/${c.stored_name}" target="_blank" rel="noopener">View resume</a>
          <button class="action-link" data-action="timeline" data-id="${c.id}" data-name="${escapeHtml(c.name)}">Timeline</button>
          <button class="action-link is-good" data-action="shortlisted" data-id="${c.id}">Shortlist</button>
          <button class="action-link is-bad" data-action="rejected" data-id="${c.id}">Reject</button>
        </div>
      </div>
    `;

    el.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        if (action === "timeline") openTimeline(btn.dataset.id, btn.dataset.name);
        else setCandidateStatus(btn.dataset.id, action);
      });
    });

    return el;
  }

  async function setCandidateStatus(candidateId, status) {
    try {
      const res = await fetch(`/api/candidates/${candidateId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't update status.");
      const cand = state.candidates.find(c => c.id === candidateId);
      if (cand) cand.status = status;
      renderResults();
    } catch (err) {
      alert(err.message);
    }
  }

  // ---------- Timeline modal ----------
  const timelineModal = document.getElementById("timeline-modal");
  const timelineList = document.getElementById("timeline-list");
  const timelineTitle = document.getElementById("timeline-title");

  document.getElementById("timeline-close").addEventListener("click", () => { timelineModal.hidden = true; });
  timelineModal.addEventListener("click", e => { if (e.target === timelineModal) timelineModal.hidden = true; });

  async function openTimeline(candidateId, name) {
    timelineTitle.textContent = `Timeline — ${name}`;
    timelineList.innerHTML = "<li>Loading…</li>";
    timelineModal.hidden = false;
    try {
      const res = await fetch(`/api/candidates/${candidateId}/timeline`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't load timeline.");
      timelineList.innerHTML = "";
      data.events.forEach(ev => {
        const li = document.createElement("li");
        li.innerHTML = `<span class="timeline-event">${escapeHtml(ev.event)}</span>
          <span class="timeline-time">${formatDate(ev.created_at)}</span>
          ${ev.note ? `<span class="timeline-note">${escapeHtml(ev.note)}</span>` : ""}`;
        timelineList.appendChild(li);
      });
    } catch (err) {
      timelineList.innerHTML = `<li>${escapeHtml(err.message)}</li>`;
    }
  }

  // ---------- History ----------
  const historyList = document.getElementById("history-list");

  async function loadHistory() {
    historyList.innerHTML = "<p class='empty-note'>Loading…</p>";
    try {
      const res = await fetch("/api/jobs");
      const jobs = await res.json();
      if (!jobs.length) {
        historyList.innerHTML = "<p class='empty-note'>No roles opened yet.</p>";
        return;
      }
      historyList.innerHTML = "";
      jobs.forEach(job => {
        const item = document.createElement("div");
        item.className = "history-item";
        item.innerHTML = `
          <div>
            <h3>${escapeHtml(job.title)}</h3>
            <p>Opened ${formatDate(job.created_at)}</p>
          </div>
          <span class="history-count">${job.candidate_count} applicant${job.candidate_count === 1 ? "" : "s"} · ${job.shortlisted_count} shortlisted</span>
        `;
        item.addEventListener("click", () => openPastJob(job.id, job.title));
        historyList.appendChild(item);
      });
    } catch {
      historyList.innerHTML = "<p class='empty-note'>Couldn't load past roles.</p>";
    }
  }

  async function openPastJob(jobId, title) {
    showLoading("Pulling up that role…");
    try {
      const res = await fetch(`/api/jobs/${jobId}/candidates`);
      const data = await res.json();
      state.jobId = jobId;
      state.jobTitle = title;
      state.candidates = data.candidates;
      renderResults();
      showView("results");
    } finally {
      hideLoading();
    }
  }

  // ---------- Helpers ----------
  function setStatus(el, message, ok) {
    el.textContent = message;
    el.classList.toggle("is-ok", !!ok && !!message);
  }

  function showLoading(text) {
    document.getElementById("loading-text").textContent = text;
    document.getElementById("loading-overlay").hidden = false;
  }
  function hideLoading() {
    document.getElementById("loading-overlay").hidden = true;
  }

  function formatDate(isoLike) {
    const d = new Date(isoLike.replace(" ", "T") + "Z");
    return isNaN(d) ? isoLike : d.toLocaleString();
  }

  function escapeHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, m => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[m]));
  }
})();
