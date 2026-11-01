document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const p = document.querySelector('#pageContent');
  const id = new URLSearchParams(location.search).get('id');
  if (!id) { p.innerHTML = '<div class="alert alert-danger">A job must be selected.</div>'; return; }
  try {
    const j = await API.get(`/api/jobs/${encodeURIComponent(id)}`);
    p.innerHTML = `<a href="jobs.html"><i class="bi bi-arrow-left me-2"></i>Back to Jobs</a><div class="page-head mt-3"><div><h1 class="page-title">${UI.esc(j.title || 'Untitled job')} <span class="badge-soft ${j.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${UI.esc(j.status)}</span></h1><p class="page-subtitle">${UI.esc(j.department || '—')} · Created ${j.created_at ? new Date(j.created_at).toLocaleDateString() : '—'}</p></div></div>
      <div class="tab-nav"><button class="active">Overview</button><button onclick="location.href='candidates.html?job_id=${encodeURIComponent(id)}'">Candidates</button><button onclick="location.href='final-results.html?job_id=${encodeURIComponent(id)}'">Results</button></div>
      <div class="detail-grid"><div class="card-panel p-4"><h3 class="fs-6">Job Information</h3><p><b>Department</b><br>${UI.esc(j.department || '—')}</p><p><b>Experience Level</b><br>${UI.esc(j.experience_level || '—')}</p><p><b>Number of Positions</b><br>${j.positions ?? '—'}</p><p><b>Created On</b><br>${j.created_at ? new Date(j.created_at).toLocaleString() : '—'}</p></div><div class="card-panel p-4"><h3 class="fs-6">Recruitment workflow</h3><p>Review ATS-ranked candidates, persist the shortlist, create link-only examination invitations, and inspect final results.</p><a class="btn btn-primary" href="candidates.html?job_id=${encodeURIComponent(id)}">Review candidates</a></div></div>`;
  } catch (error) { p.innerHTML = `<div class="alert alert-danger">${UI.esc(error.message)}</div>`; }
});
