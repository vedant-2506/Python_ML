document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const p = document.querySelector('#pageContent');
  try {
    const s = await API.get('/api/dashboard/summary');
    const user = JSON.parse(localStorage.getItem('rankresume_user') || '{}');
    const jobs = s.recent_jobs || [];
    p.innerHTML = `<div class="page-head"><div><h1 class="page-title">Welcome back, ${UI.esc(user.name || 'Recruiter')}!</h1><p class="page-subtitle">Here’s what’s happening with your hiring pipeline today.</p></div><a class="btn btn-primary" href="create-job.html"><i class="bi bi-plus-lg me-2"></i>Create Job</a></div>
      <div class="stat-grid">${[['briefcase','Total Jobs',s.total_jobs ?? s.jobs ?? 0,'Active job postings'],['people','Total Candidates',s.candidates ?? 0,'Across active jobs'],['person-check','Shortlisted',s.shortlisted ?? 0,'Exam invitations'],['trophy','Completed Exams',s.hired ?? 0,'Final results']].map(x => `<div class="card-panel stat-card"><div><div class="stat-caption">${x[1]}</div><div class="stat-number">${x[2]}</div><div class="stat-caption">${x[3]}</div></div><div class="stat-icon"><i class="bi bi-${x[0]}"></i></div></div>`).join('')}</div>
      <div class="card-panel table-card"><div class="table-head"><h2 class="fs-5 m-0">Active Jobs</h2><a href="jobs.html">View All <i class="bi bi-arrow-right"></i></a></div>
      <div class="table-responsive"><table class="table"><thead><tr><th>Job Title</th><th>Department</th><th>Candidates</th><th>Status</th><th>Created On</th></tr></thead><tbody>${jobs.map(j => `<tr data-id="${j.jd_id}" style="cursor:pointer"><td><b>${UI.esc(j.title || 'Untitled job')}</b></td><td>${UI.esc(j.department || '—')}</td><td>${j.candidate_count ?? 0}</td><td><span class="badge-soft badge-active">${UI.esc(j.status)}</span></td><td>${j.created_at ? new Date(j.created_at).toLocaleDateString() : '—'}</td></tr>`).join('') || '<tr><td colspan="5"><div class="empty-state">No active jobs yet.</div></td></tr>'}</tbody></table></div></div>`;
    p.querySelectorAll('tbody tr[data-id]').forEach(row => row.onclick = () => location.href = `job-details.html?id=${row.dataset.id}`);
  } catch (error) {
    p.innerHTML = `<div class="alert alert-danger">Unable to load dashboard: ${UI.esc(error.message || 'Request failed')}</div>`;
  }
});
