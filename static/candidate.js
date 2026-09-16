(() => {
  let pendingApplyJobId = null;
  let pendingApplyFile = null;

  // ---------- Nav ----------
  const views = {
    browse: document.getElementById("view-browse"),
    applications: document.getElementById("view-applications"),
  };
  const navLinks = document.querySelectorAll(".nav-link[data-view]");

  function showView(name) {
    Object.entries(views).forEach(([key, el]) => { el.hidden = key !== name; });
    navLinks.forEach(btn => btn.classList.toggle("is-active", btn.dataset.view === name));
    if (name === "browse") loadJobs();
    if (name === "applications") loadApplications();
  }

  navLinks.forEach(btn => btn.addEventListener("click", () => showView(btn.dataset.view)));

  document.getElementById("logout-btn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });

  // ---------- Browse jobs ----------
  const jobsList = document.getElementById("jobs-list");

  async function loadJobs() {
    jobsList.innerHTML = "<p class='empty-note'>Loading open roles…</p>";
    try {
      const res = await fetch("/api/open-jobs");
      const jobs = await res.json();
      if (!jobs.length) {
        jobsList.innerHTML = "<p class='empty-note'>No open roles right now — check back soon.</p>";
        return;
      }
      jobsList.innerHTML = "";
      jobs.forEach(job => jobsList.appendChild(buildJobCard(job)));
    } catch {
      jobsList.innerHTML = "<p class='empty-note'>Couldn't load open roles.</p>";
    }
  }

  function buildJobCard(job) {
    const el = document.createElement("article");
    el.className = "job-card";
    const skillsHtml = (job.required_skills || []).map(s => `<span class="chip plain">${escapeHtml(s)}</span>`).join("");
    const snippet = job.description.length > 220 ? job.description.slice(0, 220) + "…" : job.description;
    el.innerHTML = `
      <div class="job-card-top">
        <h3>${escapeHtml(job.title)}</h3>
        <span class="job-card-recruiter">Posted by ${escapeHtml(job.recruiter_name)}</span>
      </div>
      <p class="job-card-desc">${escapeHtml(snippet)}</p>
      <div class="skill-row">${skillsHtml}</div>
      <div class="dossier-actions">
        ${job.already_applied
          ? `<span class="status-badge status-applied">already applied</span>`
          : `<button class="btn-primary btn-small" data-apply="${job.id}" data-title="${escapeHtml(job.title)}">Apply</button>`}
      </div>
    `;
    const applyBtn = el.querySelector("[data-apply]");
    if (applyBtn) {
      applyBtn.addEventListener("click", () => openApplyModal(job.id, job.title));
    }
    return el;
  }

  // ---------- Apply modal ----------
  const applyModal = document.getElementById("apply-modal");
  const applyDropzone = document.getElementById("apply-dropzone");
  const applyFileInput = document.getElementById("apply-file-input");
  const applyFileName = document.getElementById("apply-file-name");
  const applySubmitBtn = document.getElementById("apply-submit-btn");
  const applyStatus = document.getElementById("apply-status");
  const applyJobTitleEl = document.getElementById("apply-job-title");

  function openApplyModal(jobId, title) {
    pendingApplyJobId = jobId;
    pendingApplyFile = null;
    applyJobTitleEl.textContent = `Apply — ${title}`;
    applyFileName.textContent = "";
    applyStatus.textContent = "";
    applySubmitBtn.disabled = true;
    applyModal.hidden = false;
  }

  document.getElementById("apply-close").addEventListener("click", () => { applyModal.hidden = true; });
  applyModal.addEventListener("click", e => { if (e.target === applyModal) applyModal.hidden = true; });

  applyDropzone.addEventListener("click", () => applyFileInput.click());
  applyDropzone.addEventListener("dragover", e => { e.preventDefault(); applyDropzone.classList.add("is-dragover"); });
  applyDropzone.addEventListener("dragleave", () => applyDropzone.classList.remove("is-dragover"));
  applyDropzone.addEventListener("drop", e => {
    e.preventDefault();
    applyDropzone.classList.remove("is-dragover");
    if (e.dataTransfer.files.length) setApplyFile(e.dataTransfer.files[0]);
  });
  applyFileInput.addEventListener("change", () => {
    if (applyFileInput.files.length) setApplyFile(applyFileInput.files[0]);
  });

  function setApplyFile(file) {
    const allowed = [".pdf", ".docx", ".doc", ".txt"];
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) {
      applyStatus.textContent = "Please choose a PDF, DOCX, or TXT file.";
      return;
    }
    pendingApplyFile = file;
    applyFileName.textContent = `${file.name} · ${Math.round(file.size / 1024)}kb`;
    applySubmitBtn.disabled = false;
  }

  applySubmitBtn.addEventListener("click", async () => {
    if (!pendingApplyJobId || !pendingApplyFile) return;
    const form = new FormData();
    form.append("resume", pendingApplyFile);

    showLoading("Submitting your application…");
    applySubmitBtn.disabled = true;
    try {
      const res = await fetch(`/api/jobs/${pendingApplyJobId}/apply`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't submit that application.");
      applyModal.hidden = true;
      showView("applications");
    } catch (err) {
      applyStatus.textContent = err.message;
    } finally {
      hideLoading();
      applySubmitBtn.disabled = false;
    }
  });

  // ---------- My applications ----------
  const applicationsList = document.getElementById("applications-list");

  async function loadApplications() {
    applicationsList.innerHTML = "<p class='empty-note'>Loading…</p>";
    try {
      const res = await fetch("/api/my-applications");
      const apps = await res.json();
      if (!apps.length) {
        applicationsList.innerHTML = "<p class='empty-note'>You haven't applied to anything yet — browse open roles to get started.</p>";
        return;
      }
      applicationsList.innerHTML = "";
      apps.forEach(a => applicationsList.appendChild(buildApplicationCard(a)));
    } catch {
      applicationsList.innerHTML = "<p class='empty-note'>Couldn't load your applications.</p>";
    }
  }

  function buildApplicationCard(a) {
    const el = document.createElement("article");
    el.className = "application-card";
    const matched = a.matched_skills || [];
    const missing = a.missing_skills || [];
    const chipHtml = [
      ...matched.map(s => `<span class="chip matched">${escapeHtml(s)} ✓</span>`),
      ...missing.map(s => `<span class="chip missing">${escapeHtml(s)}</span>`),
    ].join("");
    el.innerHTML = `
      <div class="job-card-top">
        <h3>${escapeHtml(a.job_title)}</h3>
        <span class="status-badge status-${a.status}">${a.status}</span>
      </div>
      <p class="job-card-desc">Applied ${formatDate(a.applied_at)} · Match score ${Math.round(a.score)}</p>
      <div class="skill-row">${chipHtml}</div>
      <div class="dossier-actions">
        <button class="action-link" data-id="${a.id}" data-title="${escapeHtml(a.job_title)}">View timeline</button>
      </div>
    `;
    el.querySelector("[data-id]").addEventListener("click", () => openTimeline(a.id, a.job_title));
    return el;
  }

  // ---------- Timeline modal ----------
  const timelineModal = document.getElementById("timeline-modal");
  const timelineList = document.getElementById("timeline-list");
  const timelineTitle = document.getElementById("timeline-title");

  document.getElementById("timeline-close").addEventListener("click", () => { timelineModal.hidden = true; });
  timelineModal.addEventListener("click", e => { if (e.target === timelineModal) timelineModal.hidden = true; });

  async function openTimeline(candidateId, jobTitle) {
    timelineTitle.textContent = `Timeline — ${jobTitle}`;
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
          <span class="timeline-time">${formatDate(ev.created_at)}</span>`;
        timelineList.appendChild(li);
      });
    } catch (err) {
      timelineList.innerHTML = `<li>${escapeHtml(err.message)}</li>`;
    }
  }

  // ---------- Helpers ----------
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

  // initial view
  showView("browse");
})();
