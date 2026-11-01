(() => {
  const token = new URLSearchParams(location.search).get('token');
  if (!token) { if (location.pathname.includes('exam-start')) location.href='exam-invalid.html'; return; }
  const state = { questions:[], answers:{}, index:0, stage:1, endsAt:0, offset:0, warnings:0, stats:{}, events:[] };
  const sentenceCount = text => (text.trim().match(/[.!?]+(?=\s|$)/g)||[]).length;
  const saveDraft = async order => {
    const text=state.answers[order]||''; sessionStorage.setItem(`rr:${token}:${order}`,text);
    try { await API.put(`/api/exam/${encodeURIComponent(token)}/answers/${order}`,{text},{public:true}); } catch (_) {}
  };
  const pushEvent = (event_type, question_order=null, meta={}) => state.events.push({event_type,question_order,meta,occurred_at:new Date().toISOString()});
  const flushEvents = async () => {
    if (!state.events.length && !Object.keys(state.stats).length) return;
    const stats=Object.values(state.stats); const events=state.events.splice(0);
    try { await API.post(`/api/exam/${encodeURIComponent(token)}/events`,{events,typing_stats:stats},{public:true}); } catch (_) {}
  };
  const showError = (error, context) => {
    const status = error?.status;
    if (status === 404 || status === 410 || status === 409) {
      const reason = encodeURIComponent(error.message || 'This exam invitation is unavailable.');
      if (!location.pathname.includes('exam-invalid')) location.href=`exam-invalid.html?reason=${reason}`;
      return;
    }
    const target = document.querySelector('#error') || document.querySelector('#content');
    if (target) target.textContent = `${context}: ${error?.message || 'The server could not complete this request.'}`;
  };
  async function loadInfo() {
    try {
      const info=await API.get(`/api/exam/${encodeURIComponent(token)}/info`,{public:true});
      if(document.querySelector('#title')) { document.querySelector('#title').textContent=`Assessment: ${info.job_title}`; document.querySelector('#company').textContent=`${info.company_name} · ${info.candidate_name}`; }
      if(document.querySelector('#start')) document.querySelector('#start').onclick=async()=>{try{await API.post(`/api/exam/${encodeURIComponent(token)}/start`,{}, {public:true});location.href=`exam.html?token=${encodeURIComponent(token)}`;}catch(e){document.querySelector('#error').textContent=e.message;}};
    } catch (error) { showError(error, 'Unable to validate this invitation'); }
  }
  async function loadState() {
    const data=await API.get(`/api/exam/${encodeURIComponent(token)}/state`,{public:true});
    const previousStage=state.stage;
    state.stage=data.stage;
    state.questions=data.questions.filter(q=>state.stage===1?q.stage===1:q.stage===2);
    if(previousStage!==state.stage) state.index=0;
    state.endsAt=Date.parse(data.ends_at); state.offset=Date.parse(data.server_time)-Date.now();
    state.answers={...data.drafts}; state.questions.forEach(q=>{if(state.answers[q.order]===undefined)state.answers[q.order]=sessionStorage.getItem(`rr:${token}:${q.order}`)||'';});
    draw();
  }
  function draw() {
    const nav=document.querySelector('#navigator'); if(!nav)return;
    nav.innerHTML=Array.from({length:10},(_,i)=>{const order=i+1,q=state.questions.find(x=>x.order===order),locked=!q;return `<button ${locked?'disabled':''} class="${order===state.questions[state.index]?.order?'current ':''}${state.answers[order]?.trim()?'answered':''}" data-order="${order}">${locked?'🔒 ':''}${order}</button>`}).join('');
    nav.querySelectorAll('button:not(:disabled)').forEach(b=>b.onclick=async()=>{await saveDraft(state.questions[state.index].order);state.index=state.questions.findIndex(q=>q.order===+b.dataset.order);draw();});
    const q=state.questions[state.index]; if(!q)return;
    document.querySelector('#candidate').textContent=document.querySelector('#candidate').textContent||'Candidate assessment';
    const last=state.index===state.questions.length-1, section=state.stage===1?'Section 1 of 2 (Manual Questions)':'Section 2 of 2 (AI Generated Questions)', count=state.stage===1?`${state.index+1} / 6`:`${state.index+1} / 4`;
    document.querySelector('#content').innerHTML=`<div class="section-banner">${section}<span style="float:right">${count}</span></div><div class="question-meta"><strong>Question ${q.order}</strong><span><span class="difficulty">${q.difficulty}</span> &nbsp; ${q.max_marks} marks</span></div><p class="question-text">${escapeHtml(q.question)}</p><label for="answer"><strong>Your Answer</strong></label><textarea id="answer" class="answer-box" spellcheck="false" autocomplete="off" autocapitalize="off" maxlength="3000">${escapeHtml(state.answers[q.order]||'')}</textarea><div id="notice" class="notice"></div><div id="sentences" class="sentence-count"></div><div class="exam-footer"><button id="prev" class="btn-exam secondary" ${state.index===0?'disabled':''}>Previous</button><button id="next" class="btn-exam">${last?(state.stage===1?'Submit Section 1':'Submit Exam'):'Next'}</button></div>`;
    const answer=document.querySelector('#answer'), update=()=>{state.answers[q.order]=answer.value;const n=sentenceCount(answer.value);document.querySelector('#sentences').textContent=`Sentences: ${n} (aim for 5–6)`;document.querySelector('#sentences').classList.toggle('over',n>6);};
    update(); let timer; answer.oninput=()=>{update();clearTimeout(timer);timer=setTimeout(()=>saveDraft(q.order),3000);};
    answer.onblur=()=>saveDraft(q.order); ['paste','copy','cut','drop','contextmenu'].forEach(type=>answer.addEventListener(type,e=>{e.preventDefault();document.querySelector('#notice').textContent='Pasting is disabled';pushEvent(`${type}_attempt`,q.order);}));
    answer.onkeydown=e=>{const s=state.stats[q.order]||{question_order:q.order,keystrokes:0,backspaces:0,paste_attempts:0,interkeys:[]};if(e.key==='Backspace')s.backspaces++;else if(e.key.length===1)s.keystrokes++;state.stats[q.order]=s;};
    document.querySelector('#prev').onclick=async()=>{await saveDraft(q.order);state.index--;draw();};
    document.querySelector('#next').onclick=async()=>{await saveDraft(q.order);if(last) await submit();else{state.index++;draw();}};
  }
  function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  async function submit() {
    const path=state.stage===1?'submit-stage1':'submit';
    if(!confirm(state.stage===1?'You cannot return to Section 1 after submitting. Continue?':'Submit the exam now?'))return;
    document.querySelector('#content').innerHTML='<div class="preparing"><h2>Preparing Section 2…</h2><p>Please keep this tab open.</p></div>';
    try { await API.post(`/api/exam/${encodeURIComponent(token)}/${path}`,{}, {public:true}); if(state.stage===1){await waitStage2();await loadState();}else location.href='exam-submitted.html'; } catch(e){document.querySelector('#content').innerHTML=`<div class="preparing"><h2>Something went wrong</h2><p class="notice">${escapeHtml(e.message)}</p><button id="retry" class="btn-exam">Retry</button></div>`;document.querySelector('#retry').onclick=()=>submit();}
  }
  async function waitStage2(){for(let i=0;i<30;i++){const r=await API.get(`/api/exam/${encodeURIComponent(token)}/stage2-status`,{public:true});if(r.status==='ready')return;await new Promise(x=>setTimeout(x,2000));}throw Error('Stage 2 is taking longer than expected.');}
  function clock(){const seconds=Math.max(0,Math.floor((state.endsAt-(Date.now()+state.offset))/1000)),m=String(Math.floor(seconds/60)).padStart(2,'0'),s=String(seconds%60).padStart(2,'0'),el=document.querySelector('#clock');if(!el)return;el.textContent=`${m}:${s}`;el.classList.toggle('warn',seconds<600&&seconds>=300);el.classList.toggle('danger',seconds<300);if(seconds===0){submit();return;}setTimeout(clock,1000);}
  document.addEventListener('visibilitychange',()=>{if(document.hidden){state.warnings++;pushEvent('tab_hidden');document.querySelector('#warningCount').textContent=`Integrity warnings: ${state.warnings}`;}});
  window.addEventListener('blur',()=>{state.warnings++;pushEvent('window_blur');if(document.querySelector('#warningCount'))document.querySelector('#warningCount').textContent=`Integrity warnings: ${state.warnings}`;});
  window.addEventListener('beforeunload',e=>{if(location.pathname.includes('exam.html') && state.questions.length && state.endsAt > Date.now()){e.preventDefault();e.returnValue='Your exam is in progress.';}});
  setInterval(flushEvents,15000);
  if(location.pathname.includes('exam-start'))loadInfo(); else if(location.pathname.includes('exam.html'))loadState().then(clock).catch(error=>showError(error,'Unable to load the examination'));
})();
