const charts={};
const chartStatuses=['passed','failed','needs_review','blocked','not_tested'];
const chartColors=['#167454','#b53249','#906300','#5b657a','#ccd2df'];
function drawChart(id,fallback,type,labels,values,colors,axisTitle='Number of test cases')
{
  if(charts[id]){charts[id].destroy();delete charts[id];}
  
  const canvas=document.getElementById(id), empty=document.getElementById(fallback);
  canvas.hidden=!values.length||!window.Chart;empty.hidden=values.length>0&&!!window.Chart;
  if(!values.length){empty.textContent='No recorded results yet.';return;}
  if(!window.Chart){empty.textContent=labels.map((x,i)=>x+': '+values[i]).join(' | ');return;}
  Chart.defaults.color='#253047';Chart.defaults.font.family='Times New Roman';Chart.defaults.font.size=16;
  charts[id]=new Chart(canvas,{type,data:{labels,datasets:[{label:axisTitle,data:values,backgroundColor:colors,borderWidth:0,borderRadius:type==='bar'?5:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:type==='doughnut',position:'bottom',labels:{boxWidth:14,font:{size:16}}},tooltip:{callbacks:{label:c=>c.label+': '+c.raw+(id==='durationChart'?' seconds':' test cases')}}},scales:type==='bar'?{y:{beginAtZero:true,title:{display:true,text:axisTitle},ticks:{precision:0},grid:{color:'#e3e7ef'}},x:{grid:{display:false},ticks:{font:{size:15},autoSkip:false}}}:{},cutout:type==='doughnut'?'65%':undefined}});
}
function renderDashboard(){
  const all=state.runs.flatMap(r=>r.results), latest=[...state.runs].sort((a,b)=>b.started_at.localeCompare(a.started_at))[0];
  const count=s=>all.filter(r=>r.status===s).length;
  const n=count('passed')+count('failed');const rate=n?(100*count('passed')/n).toFixed(1)+'%':'Not available';
  const metrics=[['Saved projects',state.projects.length],['Test runs',state.runs.length],['Pass rate - all recorded runs',rate],['Passed tests',count('passed')],['Failed tests',count('failed')],['Not run or needs review',count('blocked')+count('needs_review')+count('not_tested')]];
  document.getElementById('stats').innerHTML=metrics.map(([name,value])=>'<div class="stat"><span>'+name+'</span><strong>'+value+'</strong></div>').join('');
  const results=latest?.results||[];
  document.getElementById('latestRunContext').textContent=latest?'Showing latest run: '+runLabel(latest):'Upload a project and start a test run to see real results.';
  drawChart('outcomeChart','outcomeFallback','doughnut',chartStatuses.map(s=>statusNames[s]),results.length?chartStatuses.map(s=>results.filter(r=>r.status===s).length):[],chartColors);
  const cats=[...new Set(results.map(r=>r.category))];
  drawChart('categoryChart','categoryFallback','bar',cats.map(c=>categoryNames[c]||c),cats.map(c=>results.filter(r=>r.category===c).length),'#5364c7');
  document.getElementById('categorySummary').innerHTML=cats.length?'<div class="table-scroll"><table><caption>Latest run: counts and pass rates by test type</caption><thead><tr><th>Test type</th><th>Total</th><th>Passed</th><th>Failed</th><th>Needs review</th><th>Could not run / not run</th><th>Pass rate</th></tr></thead><tbody>'+cats.map(c=>{const rows=results.filter(r=>r.category===c),ct=s=>rows.filter(r=>r.status===s).length,scored=ct('passed')+ct('failed');return '<tr><td>'+escapeHtml(categoryNames[c]||c)+'</td><td>'+rows.length+'</td><td>'+ct('passed')+'</td><td>'+ct('failed')+'</td><td>'+ct('needs_review')+'</td><td>'+(ct('blocked')+ct('not_tested'))+'</td><td>'+(scored?(100*ct('passed')/scored).toFixed(1)+'%':'Not scored')+'</td></tr>';}).join('')+'</tbody></table></div>':'No test categories recorded yet.';
  const timed=[...state.runs].filter(r=>r.finished_at).sort((a,b)=>a.started_at.localeCompare(b.started_at)).slice(-6);
  const seconds=r=>Math.max(0,(new Date(r.finished_at)-new Date(r.started_at))/1000);
  drawChart('durationChart','durationFallback','bar',timed.map(runNumber),timed.map(r=>Number(seconds(r).toFixed(1))),'#167b76','Elapsed time in seconds');
  document.getElementById('durationDetails').innerHTML=timed.length?'<div class="table-scroll"><table><caption>Run names, start times and measured duration</caption><thead><tr><th>Run</th><th>Project</th><th>Started</th><th>Time taken</th></tr></thead><tbody>'+timed.map(r=>'<tr><td>'+runNumber(r)+'</td><td>'+escapeHtml(projectName(state.projects.find(p=>p.id===r.project_id)))+'</td><td>'+escapeHtml(new Date(r.started_at).toLocaleString())+'</td><td>'+seconds(r).toFixed(1)+' seconds</td></tr>').join('')+'</tbody></table></div>':'';
  document.getElementById('history').className=state.runs.length?'':'empty';
  document.getElementById('history').innerHTML=state.runs.length?[...state.runs].sort((a,b)=>b.started_at.localeCompare(a.started_at)).slice(0,5).map(r=>'<div class="history-row"><span><strong>'+runNumber(r)+'</strong> - '+escapeHtml(projectName(state.projects.find(p=>p.id===r.project_id)))+'<br><small>'+escapeHtml(new Date(r.started_at).toLocaleString())+'</small></span><span class="badge '+(r.status==='completed'?'passed':'blocked')+'">'+escapeHtml(statusNames[r.status]||r.status)+'</span><button data-run="'+r.id+'">View results</button></div>').join(''):'Your runs will appear here.';
  const help={static:'Inspect source files for syntax errors and risky patterns.',functional:'Check whether the bot API returns the expected response.',hallucination:'Compare answers with reference facts you supply.',bias:'Compare responses to equivalent user scenarios.',injection:'Check responses to attempts to override bot instructions.',guardrails:'Check whether responses follow your safety policy.',multiturn:'Check whether the bot remembers conversation context.',language:'Review requested language, tone and politeness.',performance:'Measure response speed and request reliability.',security:'Scan source code for possible security issues.'};
  document.getElementById('suiteCards').innerHTML=Object.entries(help).map(([id,description])=>'<div class="suite"><h3>'+categoryNames[id]+'</h3><p>'+description+'</p><p><strong>'+results.filter(r=>r.category===id).length+' cases recorded in the latest run</strong></p></div>').join('');
}

