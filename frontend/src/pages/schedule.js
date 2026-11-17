import {schedule} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,fmt,notify} from '../utils/dom.js';
import {PlanStatus} from '../constants/enums.js';

const chip=p=>'<span class="status '+esc(p.status)+'">'+esc(PlanStatus[p.status]||p.status)+'</span>';
const conflicts=p=>(p.conflicts||[]).map(c=>'<p class="warning">'+esc(c.message)+'</p>').join('');
const held=p=>p.status==='pending_reschedule'?'<p class="warning">受工位封闭影响待重排；保留日期 '+(p.slots.map(esc).join('、')||'无')+' 仍占用工位，未解决前新案不能挤占。</p>':'';

function planItem(p,stations,canWrite,today){
 const range=p.status==='draft'?esc(p.start_date)+' 起 '+p.days+' 天（试排未占用）':(p.slots.length?esc(p.slots[0])+' → '+esc(p.slots[p.slots.length-1]):'无占用日期');
 const acts=[];
 if(canWrite){
  if(p.status==='draft')acts.push('<button class="small primary" data-confirm="'+p.id+'">确认并占用工位</button>');
  if(p.status==='confirmed'||p.status==='pending_reschedule')acts.push('<details class="reschedule"><summary>改期</summary><form class="reschedule-form" data-plan="'+p.id+'" data-key="rs-'+p.id+'-'+Math.random().toString(36).slice(2)+'"><label>检修站<select name="station_id">'+stations.map(s=>'<option value="'+s.id+'" '+(s.id===p.station_id?'selected':'')+'>'+esc(s.name)+' · 每日 '+s.bays+' 工位</option>').join('')+'</select></label><label>新开始日期<input type="date" name="start_date" required min="'+today+'" value="'+esc(p.start_date)+'"></label><button type="submit" class="small primary">整案换位</button><p class="hint">原占用保留到新日期全部可用；中断或重试不会重复排单。</p></form></details>');
  if(p.status!=='cancelled')acts.push('<button class="small" data-cancel="'+p.id+'">取消</button>');
 }
 return '<article class="plan-item"><div class="plan-head"><strong>'+esc(p.fleet_no)+' · '+esc(p.model)+'</strong>'+chip(p)+'</div><p>'+esc(p.station)+' · '+range+' · 检修 '+p.days+' 天<br>批准里程 '+fmt(p.approved_km)+' km · 到期日 '+esc(p.due_date)+'</p>'+conflicts(p)+held(p)+(acts.length?'<div class="plan-actions">'+acts.join('')+'</div>':'')+'</article>';
}

export async function schedulePage(){
 const [boot,cal,plans,closures]=await Promise.all([schedule.bootstrap(),schedule.calendar(),schedule.plans(),schedule.closures()]);
 const canWrite=['admin','analyst'].includes(session.user.role),isAdmin=session.user.role==='admin';
 const today=boot.today,tomorrow=new Date(new Date(today+'T00:00:00').getTime()+86400000).toISOString().slice(0,10);
 const vehicleOpts=boot.vehicles.map(v=>'<option value="'+v.id+'">'+esc(v.fleet_no)+' · '+esc(v.model)+' · 当前 '+fmt(v.current_km)+' km · 日行 '+fmt(v.daily_km)+' km · '+(v.approved?'批准 '+fmt(v.approved_km)+' km · 到期 '+esc(v.due_date):'暂无批准里程')+'</option>').join('');
 const stationOpts=boot.stations.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · 每日 '+s.bays+' 工位</option>').join('');
 const active=plans.filter(p=>p.status!=='cancelled');
 const form='<section class="panel"><div class="section-title"><h2>试排新方案</h2><span>试排不占工位</span></div><form id="plan-form"><label>车辆<select name="vehicle_id">'+vehicleOpts+'</select></label><label>检修站<select name="station_id">'+stationOpts+'</select></label><div class="parameter-grid"><label>开始日期<input type="date" name="start_date" required min="'+today+'" value="'+tomorrow+'"></label><label>检修天数<input type="number" name="days" value="2" min="1" max="30" required></label></div><button type="submit" class="primary" '+(canWrite?'':'disabled')+'>试排并保存草稿 ↗</button><p class="hint">按已批准里程与车辆日行里程推算到期日；确认时才统一占用工位。逾期或每日出勤不足则整案不可确认，冲突列于方案卡片。</p></form></section>';
 const rules='<section class="method-sheet compact"><p class="eyebrow">SCHEDULING RULES</p><h3>编排口径</h3><ul><li>到期日 = 今天 + (已批准里程 − 当前里程) ÷ 日行里程，完工日晚于到期日即整案逾期。</li><li>确认统一占用全部检修日工位；并发确认不超工位，同车不重叠停修。</li><li>改期先保留原占用，新日期全部可用才整案换位；重试不重复排单。</li><li>工位临时封闭与确认按先受理者决定；受影响旧案转待重排，未解决前阻止新案挤占。</li></ul><p>每日出勤下限 <strong>'+boot.config.min_attendance+'</strong> 辆 · 车队 '+boot.vehicles.length+' 辆</p>'+(isAdmin?'<form id="config-form" class="config-form"><label>调整出勤下限<input type="number" name="min_attendance" min="0" value="'+boot.config.min_attendance+'" required></label><button type="submit" class="small">保存下限</button></form>':'')+'</section>';
 const planList='<section class="panel"><div class="section-title"><h2>排期方案</h2><span>'+active.length+' 案 · 草稿冲突实时校验</span></div>'+(active.length?active.map(p=>planItem(p,boot.stations,canWrite,today)).join(''):'<div class="empty">尚无检修方案。先在左侧试排，确认后统一占用工位。</div>')+'</section>';
 const calTable='<section class="panel"><div class="section-title"><h2>每日出勤与工位</h2><span>未来 '+cal.days.length+' 天 · 出勤下限 '+cal.min_attendance+' 辆</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>出勤</th>'+boot.stations.map(s=>'<th>'+esc(s.name)+'</th>').join('')+'</tr></thead><tbody>'+cal.days.map(d=>'<tr class="'+(d.fleet.ok?'':'short')+'"><td>'+esc(d.date)+' '+esc(d.weekday)+'</td><td>'+(d.fleet.ok?'':'⚠ ')+'出勤 '+d.fleet.attendance+' / '+d.fleet.total+' · 停修 '+d.fleet.down+'</td>'+d.stations.map(s=>'<td'+(s.free<0?' class="short"':'')+'>占 '+s.occupied+' · 封 '+s.closed+' · 空 '+Math.max(s.free,0)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div></section>';
 const closureList=closures.length?closures.map(c=>'<article class="plan-item"><div class="plan-head"><strong>'+esc(c.station)+' · '+esc(c.date)+'</strong><span class="status '+(c.active?'confirmed':'cancelled')+'">'+(c.active?'生效中':'已重开')+'</span></div><p>封闭 '+c.bays+' 工位 · '+esc(c.reason)+(c.displaced.length?' · 受影响方案 '+c.displaced.map(i=>'#'+i).join('、')+' 已转待重排':' · 无受影响方案')+'</p>'+(c.active&&canWrite?'<div class="plan-actions"><button class="small" data-reopen="'+c.id+'">重开工位</button></div>':'')+'</article>').join(''):'<div class="empty">暂无封闭记录。</div>';
 const closureForm='<section class="panel"><div class="section-title"><h2>工位临时封闭</h2><span>与确认按先受理者决定</span></div><form id="closure-form"><div class="parameter-grid"><label>检修站<select name="station_id">'+stationOpts+'</select></label><label>日期<input type="date" name="date" required min="'+today+'" value="'+tomorrow+'"></label></div><div class="parameter-grid"><label>封闭工位数<input type="number" name="bays" value="1" min="1" max="50" required></label><label>原因<input name="reason" required minlength="2" maxlength="200" placeholder="例如：吊装设备检修"></label></div><button type="submit" class="primary" '+(canWrite?'':'disabled')+'>登记封闭</button><p class="hint">封闭生效后超占方案转待重排并保留其余日期占用；重开后仍需人工改期解决。</p></form>'+closureList+'</section>';
 return heading('05 / CALENDAR','检修日历编排','按已批准里程、日行里程、检修天数与各站每日工位编排停修日期。')+'<div class="schedule-grid">'+form+rules+'</div>'+planList+calTable+closureForm;
}

export function bindSchedule(refresh){
 const act=async(fn,ok)=>{try{await fn();if(ok)notify(ok);}catch(e){notify(e.message,true);}await refresh();};
 const form=document.querySelector('#plan-form');
 if(form)form.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(form);act(()=>schedule.create({vehicle_id:Number(f.get('vehicle_id')),station_id:Number(f.get('station_id')),start_date:f.get('start_date'),days:Number(f.get('days'))}),'试排草稿已保存，确认后才占用工位');});
 document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=()=>act(()=>schedule.confirm(b.dataset.confirm),'已确认并统一占用工位'));
 document.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=()=>act(()=>schedule.cancel(b.dataset.cancel),'方案已取消，占用已释放'));
 document.querySelectorAll('.reschedule-form').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(form);act(()=>schedule.reschedule(form.dataset.plan,{station_id:Number(f.get('station_id')),start_date:f.get('start_date'),key:form.dataset.key}),'已整案换位到新日期');}));
 const closure=document.querySelector('#closure-form');
 if(closure)closure.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(closure);act(async()=>{const r=await schedule.close({station_id:Number(f.get('station_id')),date:f.get('date'),bays:Number(f.get('bays')),reason:f.get('reason')});notify(r.displaced.length?'已封闭，'+r.displaced.length+' 个方案转待重排':'已登记封闭');},'');});
 document.querySelectorAll('[data-reopen]').forEach(b=>b.onclick=()=>act(()=>schedule.reopen(b.dataset.reopen),'工位已重开'));
 const cfg=document.querySelector('#config-form');
 if(cfg)cfg.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(cfg);act(()=>schedule.saveConfig({min_attendance:Number(f.get('min_attendance'))}),'出勤下限已更新');});
}
