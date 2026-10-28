import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const run=promisify(execFile),root=resolve('.');
const python=process.platform==='win32'?resolve('.venv-akshare/Scripts/python.exe'):resolve('.venv-akshare/bin/python');
let pending=null,lastAutoDate='';
const shanghai=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).reduce((o,p)=>(o[p.type]=p.value,o),{});
export async function refreshEod(){
 if(pending)return pending;
 pending=run(python,[resolve('integrations/eod_market.py')],{cwd:root,timeout:10*60*1000,maxBuffer:1024*1024,env:{...process.env,PYTHONUNBUFFERED:'1'}}).then(({stdout})=>JSON.parse(stdout.trim().split(/\r?\n/).at(-1))).catch(()=>({status:'failed',error:'盘后刷新失败，已保留最近成功缓存'})).finally(()=>{pending=null});
 return pending;
}
export async function eodRefreshStatus(){try{return JSON.parse(await readFile(resolve('.runtime/eod-refresh.json'),'utf8'))}catch{return{status:pending?'refreshing':'not-run'}}}
export function startEodSchedule(){
 void refreshEod();
 const timer=setInterval(()=>{const now=shanghai(),today=`${now.year}-${now.month}-${now.day}`,minutes=Number(now.hour)*60+Number(now.minute);if(minutes>=15*60+20&&lastAutoDate!==today){lastAutoDate=today;void refreshEod()}},30*60*1000);
 timer.unref();return()=>clearInterval(timer);
}
