(() => {
'use strict';
const root = document.getElementById('dashboard');
if (!root) return;
const $ = id => document.getElementById(id);
const fmt = (v, d=0) => v==null ? '—' : new Intl.NumberFormat('vi-VN', {maximumFractionDigits:d}).format(v);
const colors = ['#c66a10', '#2474b8', '#15805a', '#8056ac'];
const ink = '#244158', muted = '#61778a', grid = '#dfe7eb';
function readable(v) {
  if (v==null) return '—';
  const h=Math.floor(v/3600), m=Math.floor(v%3600/60), s=v%60;
  return [h?`${h} giờ`:'', m?`${m} phút`:'', `${fmt(s,1)} giây`].filter(Boolean).join(' ');
}
const sim = (v, d=1) => `${fmt(v,d)} s mô phỏng`;
const text = (tag,value,cls) => { const e=document.createElement(tag); e.textContent=value; if(cls)e.className=cls; return e; };
let data=null, position=1, playing=false, page=1, jobTotal=0, timer=null, controller=null;
let selected='', jobsKey='', geometry=[], jobController=null;
const episode=$('dash-episode'), slider=$('dash-position');
function canvas(id) {
  const el=$(id), box=el.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
  el.width=Math.round(box.width*ratio); el.height=Math.round(box.height*ratio);
  const c=el.getContext('2d'); c.scale(ratio,ratio); c.font='11px system-ui';
  return {c,w:box.width,h:box.height};
}
function axes(id,maxX,maxY) {
  const {c,w,h}=canvas(id), left=46, top=15, right=w-15, bottom=h-48;
  c.strokeStyle=grid; c.fillStyle=muted;
  for(let i=0;i<=4;i++) {
    const y=bottom-(bottom-top)*i/4; c.beginPath(); c.moveTo(left,y); c.lineTo(right,y); c.stroke();
    c.fillText(fmt(maxY*i/4,1),3,y+4);
  }
  for(let i=0;i<=4;i++) {
    c.textAlign=i===4?'right':i===0?'left':'center';
    c.fillText(fmt(maxX*i/4),left+(right-left)*i/4,h-28);
  }
  c.textAlign='center'; c.fillText('Thời gian mô phỏng (s)',(left+right)/2,h-8); c.textAlign='left';
  return {c,w,h,left,right,top,bottom,x:t=>left+(right-left)*t/Math.max(1,maxX),y:v=>bottom-(bottom-top)*v/Math.max(1,maxY)};
}
function plot(id,series,keys,transform,ceiling) {
  const maxX=Math.max(1,data?.horizon||0), maxY=ceiling||Math.max(1,...series.flatMap(p=>keys.map(k=>transform(p[k]||0))));
  const a=axes(id,maxX,maxY);
  keys.forEach((key,i)=>{
    a.c.strokeStyle=id==='util-chart'?colors[2]:id==='completed-chart'?colors[3]:colors[i];
    a.c.lineWidth=1.8; a.c.beginPath();
    series.forEach((p,j)=>{
      const x=a.x(p.t), y=a.y(transform(p[key]||0));
      if(j) { a.c.lineTo(x,a.y(transform(series[j-1][key]||0))); a.c.lineTo(x,y); }
      else a.c.moveTo(x,y);
    }); a.c.stroke();
  });
  if(data?.source==='replay') {
    a.c.strokeStyle='#607d8b'; a.c.setLineDash([4,4]); a.c.beginPath();
    a.c.moveTo(a.x(data.cursor),a.top); a.c.lineTo(a.x(data.cursor),a.bottom); a.c.stroke(); a.c.setLineDash([]);
  }
  if(!series.length) { a.c.fillStyle=muted; a.c.fillText('Chưa có dữ liệu đo',a.left+10,a.h/2); }
}
function comparison() {
  const rows=data.comparison||[];
  $('comparison-chart').style.height=Math.max(230,rows.length*76+45)+'px';
  const {c,w,h}=canvas('comparison-chart');
  const max=Math.max(1,...rows.flatMap(r=>[r.p95_wait,r.mean_wait]));
  const start=83, length=Math.max(20,w-start-90);
  rows.forEach((r,i)=>{
    const y=20+i*76;
    c.fillStyle=ink; c.fillText(r.policy+' · seed '+r.seed,4,y+10);
    for(const [value,label,color,offset] of [[r.mean_wait,'TB',colors[0],19],[r.p95_wait,'p95',colors[1],38]]) {
      c.fillStyle=muted; c.fillText(label,40,y+offset+8);
      c.fillStyle=color; c.fillRect(start,y+offset,length*value/max,11);
      c.fillStyle=ink; c.fillText(fmt(value,1)+' s',start+length+6,y+offset+9);
    }
  });
  $('comparison-values').replaceChildren(...rows.map(r=>{
    const row=text('div','', 'dash-compare-row');
    row.append(text('strong',`${r.policy} · seed ${r.seed}`),text('div',`Trung bình: ${sim(r.mean_wait,2)} · p95: ${sim(r.p95_wait,2)}`),
      text('div',`Utilization: ${fmt(r.utilization==null?null:r.utilization*100,2)}% · Makespan: ${sim(r.makespan)} (${readable(r.makespan)}) · BSD: ${fmt(r.avg_bounded_slowdown,2)}`));
    return row;
  }));
  if(!rows.length) { c.fillStyle=muted; c.fillText('So sánh xuất hiện khi episode có jobs.csv.',12,h/2); }
}
function cores() {
  const {c,w,h}=canvas('core-chart'); geometry=[];
  const left=46,right=w-12,top=12,bottom=h-48,n=data.cores||32;
  const [lo,hi]=data.window||[0,1], x=t=>left+(right-left)*(t-lo)/Math.max(.000001,hi-lo), row=(bottom-top)/n;
  c.font='10px system-ui';
  for(let i=0;i<n;i++) {
    const y=top+i*row; c.fillStyle=i%2?'#edf2f5':'#f5f8fa';
    c.fillRect(left,y,right-left,Math.max(1,row-1)); c.fillStyle=muted;
    if(n<=40||i%2===0)c.fillText('c'+i,8,y+row*.8);
  }
  if(data.source==='live') {
    for(const job of data.live_core_map||[]) for(const core of job.cores) {
      if(core<0||core>=n)continue;
      const y=top+core*row; c.fillStyle=colors[Number(job.id)%colors.length];
      c.fillRect(left,y,right-left,Math.max(1,row-1));
      geometry.push({id:job.id,core,start:job.start,finish:data.cursor,a:left,b:right,y,height:row});
    }
    c.fillStyle=muted; c.fillText('Snapshot @ '+sim(data.cursor),left,h-20);
    $('timeline-note').textContent='LIVE: chỉ hiển thị allocation tại snapshot hiện tại; không phải lịch sử toàn episode.';
    $('core-summary').textContent=`Hiện có ${fmt(data.snapshot?.busy)} / ${n} core mô phỏng bận. Các core đang trống vẫn có thể đã chạy job trước đó.`;
    return;
  }
  for(const s of data.timeline||[]) {
    const a=Math.max(left,x(s.start)), b=Math.min(right,x(s.finish)), y=top+s.core*row;
    if(b<=a)continue;
    c.fillStyle=s.busy_fraction==null?colors[Number(s.id)%colors.length]:colors[1];
    c.globalAlpha=s.busy_fraction==null?1:.15+.85*s.busy_fraction;
    c.fillRect(a,y,b-a,Math.max(1,row-1)); c.globalAlpha=1;
    geometry.push({...s,a,b,y,height:row});
  }
  if(data.cursor>=lo&&data.cursor<=hi) {
    c.strokeStyle='#607d8b';c.setLineDash([3,3]);c.beginPath();c.moveTo(x(data.cursor),top);c.lineTo(x(data.cursor),bottom);c.stroke();c.setLineDash([]);
  }
  c.fillStyle=muted; c.textAlign='left'; c.fillText(fmt(lo,1),left,h-28);
  c.textAlign='right';c.fillText(fmt(hi,1),right,h-28);
  c.textAlign='center';c.fillText('Thời gian mô phỏng (s)',(left+right)/2,h-8);c.textAlign='left';
  const scope=data.timeline_view==='window'?'Cửa sổ quanh con trỏ':'Toàn episode';
  $('timeline-note').textContent=data.native_allocation?
    `${scope}: ${sim(lo)} → ${sim(hi)}. ${data.timeline_mode==='density'?'Tổng hợp mức bận từ allocation gốc; màu đậm hơn = bận nhiều hơn trong khoảng. Chọn chi tiết để xem từng job.':'Mỗi thanh màu là một job được cấp core theo CSV gốc BatSim.'}`:
    'Chưa có allocation gốc · không dựng core giả.';
  $('core-summary').textContent=data.native_allocation?`Trong toàn episode, ${data.used_cores?.length||0} / ${n} core từng được sử dụng. Phần đang xem có thể chỉ chứa một số core.`:'';
}
function render() {
  if(!data)return;
  $('worker-panel').hidden=data.live?.worker_rss_mib==null;
  $('dash-overall').textContent=`Toàn run: ${fmt(data.run_completed)} / ${fmt(data.run_total)} job-policy hoàn tất · số job input mỗi episode: ${fmt(data.total)}`;
  $('worker-metrics').textContent=data.live?.worker_rss_mib!=null?
    `CPU worker ${fmt(data.live.worker_cpu_percent,1)}% · RAM worker ${fmt(data.live.worker_rss_mib,1)} MiB · Mẫu ${data.live.at}${data.terminal?' · mẫu cuối, không phải đo hiện tại':''}`:'Run cũ chưa có mẫu CPU/RAM worker.';
  const s=data.snapshot||{}, live=data.source==='live';
  $('dash-mode').textContent=live?'● LIVE · snapshot đo mỗi ~1s':data.source==='replay'?'◷ REPLAY · dữ liệu sự kiện':'Đang chờ telemetry';
  $('dash-verification').textContent=data.verified?'PASS · đã kiểm chứng':data.terminal?'Kết quả chưa đạt PASS':'Kết quả tạm';
  $('dash-verification').className='dash-pill'+(data.verified?' pass':'');
  const items=[['Episode',data.policy?data.policy+' · seed '+data.seed:'—',data.state],
    ['Hoàn tất / tổng',fmt(s.completed)+' / '+fmt(data.total),'Theo episode đang chọn'],
    ['Job chờ / chạy',fmt(s.queued)+' / '+fmt(s.running),'Queue / Running'],
    ['Core bận',fmt(s.busy)+' / '+fmt(data.cores),fmt((s.busy||0)/Math.max(1,data.cores)*100,1)+'% mô phỏng'],
    ['Đồng hồ mô phỏng',fmt(s.t,1)+' s',readable(s.t)+' · '+(live?'snapshot':'con trỏ Replay')],
    ['Thời gian máy tính chạy',fmt(data.elapsed,1)+' s thực','Từ RUNNING · gồm kiểm chứng/thu dọn']];
  $('dash-kpis').replaceChildren(...items.map(([label,value,note])=>{
    const e=text('div','', 'dash-stat');e.append(text('span',label),text('strong',value),text('small',note));return e;
  }));
  slider.disabled=data.source!=='replay';$('dash-play').disabled=data.source!=='replay';
  $('timeline-view').disabled=data.source!=='replay';
  $('dash-clock').textContent=fmt(data.cursor,1)+' / '+sim(data.horizon);
  $('dash-replay-note').textContent=live?
    `Snapshot ${data.live_age==null?'không rõ tuổi':fmt(data.live_age,1)+' giây thực trước'}${data.live_age>8?' · CHẬM CẬP NHẬT':''}`:
    data.source==='replay'?`Tổng mô phỏng: ${readable(data.horizon)}${data.sampled?' · đường biểu đồ đã lấy mẫu; số đo tại con trỏ dùng sự kiện gốc':''}`:'Chờ episode xuất CSV.';
  plot('queue-chart',data.series||[],['queued','running'],v=>v);
  plot('util-chart',data.series||[],['busy'],v=>v/Math.max(1,data.cores)*100,100);
  plot('completed-chart',data.series||[],['completed'],v=>v,data.total||1);
  comparison();cores();
}
async function fetchJobs() {
  if(!data?.selected){$('dash-jobs').replaceChildren(text('tr','Chưa có dữ liệu job của episode.'));return;}
  if(jobController)jobController.abort();jobController=new AbortController();
  const url=new URL(root.dataset.jobs,location.href);
  url.searchParams.set('episode',data.selected);url.searchParams.set('page',page);url.searchParams.set('q',$('job-search').value);
  try {
    const response=await fetch(url,{signal:jobController.signal,cache:'no-store'});
    if(!response.ok)throw Error('Không tải được job');const result=await response.json();jobTotal=result.total;
    $('dash-jobs').replaceChildren(...result.jobs.map(j=>{
      const tr=document.createElement('tr');for(const v of [j.id,j.resources,fmt(j.submit,2),fmt(j.start,2),fmt(j.finish,2),fmt(j.wait,2)])tr.append(text('td',v));return tr;
    }));
    $('job-page').textContent=`${page} / ${Math.max(1,Math.ceil(jobTotal/25))} · ${fmt(jobTotal)} job`;
    $('job-prev').disabled=page<=1;$('job-next').disabled=page*25>=jobTotal;
  } catch(e) {if(e.name!=='AbortError')$('job-page').textContent=e.message;}
}
async function refresh() {
  if(controller)controller.abort();controller=new AbortController();
  const url=new URL(root.dataset.url,location.href);url.searchParams.set('position',position);
  url.searchParams.set('timeline_view',$('timeline-view').value);if(selected)url.searchParams.set('episode',selected);
  try {
    const response=await fetch(url,{signal:controller.signal,cache:'no-store',credentials:'same-origin'});
    if(!response.ok)throw Error('Không cập nhật được dashboard');data=await response.json();$('dash-error').hidden=true;
    const keys=new Set([...episode.options].map(o=>o.value)), options=[...data.episodes];
    if(data.live?.policy)options.push({key:data.live.policy+':'+data.live.seed,policy:data.live.policy,seed:data.live.seed});
    for(const e of options) if(!keys.has(e.key)) {const op=text('option',e.policy+' · seed '+e.seed);op.value=e.key;episode.append(op);keys.add(e.key);}
    render();const key=data.selected+':'+data.jobs_count;
    if(jobsKey!==key){jobsKey=key;page=1;fetchJobs();}
    $('dash-update').textContent='Cập nhật '+new Date().toLocaleTimeString('vi-VN');
  }catch(e){if(e.name!=='AbortError'){$('dash-error').textContent=e.message+' · đang thử lại';$('dash-error').hidden=false;}}
}
function schedule(){clearTimeout(timer);timer=setTimeout(async()=>{if(!playing)await refresh();schedule();},data?.terminal?15000:2000);}
episode.addEventListener('change',()=>{selected=episode.value;position=1;slider.value=1000;playing=false;$('dash-play').textContent='▶ Phát lại';page=1;jobsKey='';refresh();});
$('dash-refresh').addEventListener('click',refresh);$('timeline-view').addEventListener('change',refresh);
let dragTimer;slider.addEventListener('input',()=>{position=Number(slider.value)/1000;clearTimeout(dragTimer);dragTimer=setTimeout(refresh,90);});
$('dash-play').addEventListener('click',()=>{playing=!playing;$('dash-play').textContent=playing?'Ⅱ Tạm dừng':'▶ Phát lại';if(playing&&position>=1)position=0;});
setInterval(()=>{if(playing){position=Math.min(1,position+Number($('dash-speed').value));slider.value=Math.round(position*1000);refresh();if(position>=1){playing=false;$('dash-play').textContent='▶ Phát lại';}}},300);
$('job-prev').addEventListener('click',()=>{if(page>1){page--;fetchJobs();}});$('job-next').addEventListener('click',()=>{if(page*25<jobTotal){page++;fetchJobs();}});
let searchTimer;$('job-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;fetchJobs();},250);});
$('core-chart').addEventListener('mousemove',event=>{
  const box=event.currentTarget.getBoundingClientRect(),x=event.clientX-box.left,y=event.clientY-box.top;
  const s=geometry.find(s=>x>=s.a&&x<=s.b&&y>=s.y&&y<s.y+s.height);
  $('core-tooltip').textContent=!s?'Di chuột vào thanh để xem allocation gốc BatSim.':s.busy_fraction!=null?
    `Core ${s.core} · bận ${fmt(s.busy_fraction*100,1)}% trong ${sim(s.start)} → ${sim(s.finish)} · tổng hợp, không phải một job`:
    data.source==='live'?`Core ${s.core} · Job #${s.id} đang chạy từ ${sim(s.start,2)} · snapshot ${sim(data.cursor,2)}`:
    `Core ${s.core} · Job #${s.id} · ${sim(s.start,2)} → ${sim(s.finish,2)}`;
});
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(render,100);});
refresh().then(schedule);
})();