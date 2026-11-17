import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const schedule={
 bootstrap:()=>api('/schedule/bootstrap'),
 calendar:()=>api('/schedule/calendar'),
 plans:()=>api('/schedule/plans'),
 create:data=>api('/schedule/plans',{method:'POST',body:JSON.stringify(data)}),
 confirm:id=>api('/schedule/plans/'+id+'/confirm',{method:'POST'}),
 reschedule:(id,data)=>api('/schedule/plans/'+id+'/reschedule',{method:'POST',body:JSON.stringify(data)}),
 cancel:id=>api('/schedule/plans/'+id+'/cancel',{method:'POST'}),
 closures:()=>api('/schedule/closures'),
 close:data=>api('/schedule/closures',{method:'POST',body:JSON.stringify(data)}),
 reopen:id=>api('/schedule/closures/'+id+'/reopen',{method:'POST'}),
 saveConfig:data=>api('/schedule/config',{method:'PUT',body:JSON.stringify(data)})
};
