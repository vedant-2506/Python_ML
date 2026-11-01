document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const p = document.querySelector('#pageContent');
  const id = new URLSearchParams(location.search).get('id');
  if (!id) { p.innerHTML = '<div class="alert alert-danger">A candidate must be selected.</div>'; return; }
  try {
    const jobId = new URLSearchParams(location.search).get('job_id');
    const c = await API.get(`/api/candidates/${encodeURIComponent(id)}${jobId ? `?jd_id=${encodeURIComponent(jobId)}` : ''}`);
    const data = c.structured_data || {};
    const skills = data.skills || data.technical_skills || data.contact?.skills || [];
    const list = Array.isArray(skills) ? skills : String(skills).split(',').map(x => x.trim()).filter(Boolean);
    p.innerHTML = `<a href="javascript:history.back()"><i class="bi bi-arrow-left me-2"></i>Back</a><div class="card-panel profile-banner mt-3"><div class="big-avatar">${UI.initials(c.name || 'Candidate')}</div><div class="flex-grow-1"><h1 class="page-title">${UI.esc(c.name || 'Unnamed candidate')}</h1><p class="text-muted mb-1">${UI.esc(c.email || 'No email')} · ${UI.esc(c.phone || 'No phone')}</p></div></div>
      <div class="detail-grid mt-4"><div class="card-panel p-4"><h3 class="fs-6">Skills</h3>${list.map(s => `<span class="skill-chip">${UI.esc(s)}</span>`).join('') || '<p class="text-muted">No structured skills stored.</p>'}</div><div class="card-panel p-4"><h3 class="fs-6">Stored scores</h3><p>ATS score: <b>${c.ats_score ?? '—'}</b></p><p>Final score: <b>${c.final_score ?? '—'}</b></p></div></div>
      <div class="card-panel p-4 mt-3"><h3 class="fs-6">Structured resume data</h3><pre class="small mb-0">${UI.esc(JSON.stringify(data, null, 2))}</pre></div>`;
  } catch (error) { p.innerHTML = `<div class="alert alert-danger">${UI.esc(error.message)}</div>`; }
});
