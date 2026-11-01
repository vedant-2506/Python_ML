document.addEventListener('DOMContentLoaded', async () => {
  renderShell();
  const page = document.querySelector('#pageContent');
  const jobId = new URLSearchParams(location.search).get('job_id');
  page.innerHTML = `<div class="page-head"><div><h1 class="page-title">Candidates</h1><p class="page-subtitle">Review ATS-ranked candidates and send assessments.</p></div></div>
    <div class="card-panel table-card"><div class="table-head"><input id="candidateSearch" class="form-control" placeholder="Search name or email"></div>
    <div class="table-responsive"><table class="table"><thead><tr><th>Rank</th><th>Name</th><th>Email</th><th>ATS Score</th><th>Shortlist</th></tr></thead><tbody id="candidateBody"></tbody></table></div></div>
    <div class="card-panel p-3 mt-3 d-flex align-items-center gap-3"><b>Select Top N</b><input id="topN" class="form-control" type="number" min="1" max="100" value="5" style="width:80px"><button id="selectTop" class="btn btn-outline-primary">Save selection</button><button id="sendExam" class="btn btn-primary ms-auto">Create exam links</button></div><div id="shortlistStatus" class="mt-2"></div>`;
  let rows = [];
  const draw = () => {
    const query = document.querySelector('#candidateSearch').value.toLowerCase();
    document.querySelector('#candidateBody').innerHTML = rows.filter(c => `${c.candidate_name || ''}`.toLowerCase().includes(query))
      .map(c => `<tr data-id="${c.candidate_id}" style="cursor:pointer"><td>${c.rank}</td><td>${UI.esc(c.candidate_name || 'Unnamed')}</td><td>${UI.esc(c.email || '—')}</td><td>${c.ats_score ?? '—'}</td><td>${c.selected ? '<span class="badge-soft badge-active">Selected</span>' : '—'}</td></tr>`).join('') ||
      '<tr><td colspan="5"><div class="empty-state">No candidates have been processed for this job.</div></td></tr>';
    document.querySelectorAll('#candidateBody tr[data-id]').forEach(row => row.onclick = () => location.href = `candidate-detail.html?id=${row.dataset.id}&job_id=${encodeURIComponent(jobId)}`);
  };
  if (!jobId) { page.querySelector('#candidateBody').innerHTML = '<tr><td colspan="3">Select a job to view candidates.</td></tr>'; return; }
  try {
    const [result, selected] = await Promise.all([API.get(`/api/jobs/${jobId}/candidates`), API.get(`/api/jobs/${jobId}/shortlist`)]);
    rows = result.items || [];
    const selectedIds = new Set((selected.items || []).map(c => c.candidate_id));
    rows.forEach(c => c.selected = selectedIds.has(c.candidate_id));
    draw();
    document.querySelector('#shortlistStatus').textContent = `${selectedIds.size} candidate(s) currently selected.`;
  } catch (error) { page.querySelector('#candidateBody').innerHTML = `<tr><td colspan="5">${UI.esc(error.message || 'Candidates could not be loaded.')}</td></tr>`; return; }
  document.querySelector('#candidateSearch').oninput = draw;
  document.querySelector('#selectTop').onclick = async () => {
    const count = +document.querySelector('#topN').value;
    if (!Number.isInteger(count) || count < 1 || count > rows.length) { UI.toast(`Choose between 1 and ${rows.length} candidates.`, 'danger'); return; }
    try {
      await API.post(`/api/jobs/${jobId}/shortlist`, {candidate_ids: rows.slice(0, count).map(c => c.candidate_id)});
      rows.forEach((c, i) => c.selected = i < count); draw();
      document.querySelector('#shortlistStatus').textContent = `${count} candidate(s) saved to PostgreSQL.`;
      UI.toast('Shortlist saved.', 'success');
    } catch (error) { UI.toast(error.message, 'danger'); }
  };
  document.querySelector('#sendExam').onclick = async () => {
    const selected = rows.filter(c => c.selected).map(c => c.candidate_id);
    if (!selected.length) { UI.toast('Save a shortlist before creating exam links.', 'danger'); return; }
    try { showExamLinks(await API.post(`/api/jobs/${jobId}/send-exam`, { candidate_ids: selected })); }
    catch (_) { /* API displays the structured error. */ }
  };
});


function showExamLinks(result){
  const old=document.getElementById('examLinksModal');if(old)old.remove();
  const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=async t=>{try{await navigator.clipboard.writeText(t)}catch(e){const i=document.createElement('textarea');i.value=t;document.body.appendChild(i);i.select();document.execCommand('copy');i.remove()}};
  const sent=result.sent||[],skipped=result.skipped||[];
  const rows=sent.map(r=>'<tr><td>'+esc(r.rank)+'</td><td>'+esc(r.name||('Candidate '+r.candidate_id))+'</td><td style="width:50%"><input class="form-control form-control-sm" readonly value="'+esc(r.exam_link)+'"></td><td class="text-nowrap"><button class="btn btn-sm btn-outline-primary copy-link" data-link="'+esc(r.exam_link)+'">Copy</button> <a class="btn btn-sm btn-primary" target="_blank" href="'+esc(r.exam_link)+'">Open</a></td></tr>').join('');
  const skippedHtml=skipped.length?'<div class="mt-3"><b>Skipped</b><ul class="small text-muted mb-0">'+skipped.map(x=>'<li>Candidate '+esc(x.candidate_id)+': '+esc(x.reason)+'</li>').join('')+'</ul></div>':'';
  const wrap=document.createElement('div');
  wrap.id='examLinksModal';
  wrap.style.cssText='position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:2000;display:flex;align-items:center;justify-content:center;padding:16px';
  wrap.innerHTML='<div style="background:#fff;border-radius:12px;max-width:980px;width:100%;max-height:90vh;overflow:auto;padding:20px">'
    +'<div class="d-flex justify-content-between align-items-center mb-3"><h5 class="mb-0">Exam links ready ('+sent.length+')</h5><button class="btn-close" id="examLinksClose"></button></div>'
    +(sent.length?'<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Rank</th><th>Candidate</th><th>Exam link</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div><button class="btn btn-outline-primary btn-sm" id="copyAllLinks">Copy all links</button>':'<p class="text-muted">No exam links were created.</p>')
    +skippedHtml+'</div>';
  document.body.appendChild(wrap);
  wrap.querySelector('#examLinksClose').onclick=()=>wrap.remove();
  wrap.onclick=e=>{if(e.target===wrap)wrap.remove()};
  wrap.querySelectorAll('.copy-link').forEach(b=>b.onclick=async()=>{await copy(b.dataset.link);b.textContent='Copied'});
  const all=wrap.querySelector('#copyAllLinks');
  if(all)all.onclick=async()=>{await copy(sent.map(r=>(r.name||('Candidate '+r.candidate_id))+': '+r.exam_link).join('\n'));all.textContent='Copied all'};
}
