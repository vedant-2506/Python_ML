document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const page = document.querySelector('#pageContent');
  page.innerHTML = `<div class="page-head"><div><h1 class="page-title">Jobs</h1><p class="page-subtitle">Manage your job openings and hiring pipelines.</p></div><a class="btn btn-primary" href="create-job.html"><i class="bi bi-plus-lg me-2"></i>Create Job</a></div>
    <div class="card-panel table-card"><div class="table-head"><div class="filter-row"><input id="jobSearch" class="form-control" placeholder="Search jobs..."><select id="jobStatus" class="form-select"><option value="">Active jobs</option><option value="Inactive">Inactive</option><option value="Closed">Closed</option><option value="Archived">Archived</option></select></div></div>
    <div class="table-responsive"><table class="table"><thead><tr><th>Job Title</th><th>Department</th><th>Candidates</th><th>Status</th><th>Created On</th><th></th></tr></thead><tbody id="jobsBody"><tr><td colspan="6">Loading jobs...</td></tr></tbody></table></div></div>`;
  let jobs = [];
  const draw = () => {
    const query = document.querySelector('#jobSearch').value.toLowerCase();
    const filtered = jobs.filter(j => `${j.title || ''} ${j.department || ''}`.toLowerCase().includes(query));
    document.querySelector('#jobsBody').innerHTML = filtered.map(j => `<tr data-id="${j.jd_id}" style="cursor:pointer">
      <td><b>${UI.esc(j.title || 'Untitled job')}</b></td><td>${UI.esc(j.department || '—')}</td><td>${j.candidate_count ?? 0}</td>
      <td><span class="badge-soft ${j.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${UI.esc(j.status || 'Active')}</span></td>
      <td>${j.created_at ? new Date(j.created_at).toLocaleDateString() : '—'}</td><td><i class="bi bi-chevron-right"></i></td></tr>`).join('') ||
      '<tr><td colspan="6"><div class="empty-state">No jobs match your filters.</div></td></tr>';
    document.querySelectorAll('#jobsBody tr[data-id]').forEach(row => row.onclick = () => location.href = `job-details.html?id=${row.dataset.id}`);
  };
  const load = async () => {
    try {
      const result = await API.get(`/api/jobs${document.querySelector('#jobStatus').value ? `?status=${encodeURIComponent(document.querySelector('#jobStatus').value)}` : ''}`);
      jobs = result.items || []; draw();
    } catch (error) {
      document.querySelector('#jobsBody').innerHTML = `<tr><td colspan="6"><div class="alert alert-danger">${UI.esc(error.message)}</div></td></tr>`;
    }
  };
  document.querySelector('#jobSearch').oninput = draw;
  document.querySelector('#jobStatus').onchange = load;
  await load();
});
