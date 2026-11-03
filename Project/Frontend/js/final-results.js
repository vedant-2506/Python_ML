
document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const p = document.querySelector('#pageContent');
  const requested = new URLSearchParams(location.search).get('job_id');

  try {
    const jobs = await API.get('/api/jobs');
    const jobId = requested || jobs.items?.[0]?.jd_id;

    if (!jobId) {
      p.innerHTML = '<div class="empty-state">No active jobs are available.</div>';
      return;
    }

    const data = await API.get(`/api/jobs/${jobId}/results`);
    const rows = data.items || [];

    p.innerHTML = `
      <div class="page-head">
        <div>
          <h1 class="page-title">Final Results</h1>
          <p class="page-subtitle">
            Persisted ATS and examination results for the selected job.
          </p>
        </div>
        <button id="download" class="btn btn-primary">
          <i class="bi bi-download me-2"></i>Download Report
        </button>
      </div>

      <div class="mb-3">
        <label class="form-label" for="resultJob">Job</label>
        <select id="resultJob" class="form-select" style="max-width:420px">
          ${(jobs.items || []).map(j => `
            <option value="${j.jd_id}"
              ${String(j.jd_id) === String(jobId) ? 'selected' : ''}>
              ${UI.esc(j.title || 'Untitled job')}
            </option>
          `).join('')}
        </select>
      </div>

      <div class="card-panel table-card">
        <div class="table-responsive">
          <table class="table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Name</th>
                <th>Email</th>
                <th>Position</th>
                <th>ATS</th>
                <th>Final</th>
                <th>Status</th>
              </tr>
            </thead>

            <tbody>
              ${rows.map((r, i) => `
                <tr>
                  <td>${i + 1}</td>
                  <td>
                    <b>${UI.esc(r.candidate_name || 'Unnamed')}</b>
                  </td>
                  <td>${UI.esc(r.email || '—')}</td>
                  <td>${UI.esc(r.position || '—')}</td>
                  <td>${r.ats_score ?? '—'}</td>
                  <td>${r.final_result ?? '—'}</td>
                  <td>${UI.esc(r.status || '—')}</td>
                </tr>
              `).join('') || `
                <tr>
                  <td colspan="7">
                    <div class="empty-state">
                      No completed examination results for this job.
                    </div>
                  </td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;

    document.querySelector('#resultJob').onchange = e => {
      location.href = `final-results.html?job_id=${e.target.value}`;
    };

    document.querySelector('#download').onclick = async () => {
      const response = await fetch(
        `${RankResumeConfig.API_BASE_URL}/api/jobs/${jobId}/results/export`,
        {
          headers: {
            Authorization: `Bearer ${
              localStorage.getItem('rankresume_token') || ''
            }`
          }
        }
      );

      if (!response.ok) {
        UI.toast('The report could not be downloaded.', 'danger');
        return;
      }

      const blob = await response.blob();
      const link = document.createElement('a');

      link.href = URL.createObjectURL(blob);
      link.download = `job-${jobId}-results.csv`;
      link.click();

      URL.revokeObjectURL(link.href);
    };

  } catch (error) {
    p.innerHTML = `
      <div class="alert alert-danger">
        ${UI.esc(error.message)}
      </div>
    `;
  }
});
