document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const p = document.querySelector('#pageContent');
  try {
    const r = await API.get('/api/reports/summary');
    p.innerHTML = `<div class="page-head"><div><h1 class="page-title">Reports & Analytics</h1><p class="page-subtitle">Measure hiring performance from persisted recruitment data.</p></div></div>
      <div class="stat-grid">${[['people','Candidates',r.candidates ?? 0,'Across active jobs'],['speedometer2','Average ATS Score',`${r.average_ats ?? 0}%`,'Persisted ATS results'],['trophy','Average Final Mark',`${r.average_final ?? 0}%`,'Completed examinations']].map(x => `<div class="card-panel stat-card"><div><div class="stat-caption">${x[1]}</div><div class="stat-number">${x[2]}</div><div class="stat-caption">${x[3]}</div></div><div class="stat-icon"><i class="bi bi-${x[0]}"></i></div></div>`).join('')}</div>
      <div class="card-panel p-4"><h3 class="fs-6">ATS Score Distribution</h3><canvas id="atsChart" height="180"></canvas></div>`;
    if (window.Chart) new Chart(document.querySelector('#atsChart'), {type:'bar', data:{labels:['0-20','21-40','41-60','61-80','81-100'], datasets:[{label:'Candidates',data:r.ats_distribution || [0,0,0,0,0],backgroundColor:'#2563eb',borderRadius:6}]}, options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}});
  } catch (error) { p.innerHTML = `<div class="alert alert-danger">Unable to load reports: ${UI.esc(error.message)}</div>`; }
});
