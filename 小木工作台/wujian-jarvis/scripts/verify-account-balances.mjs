import assert from 'node:assert/strict';
import {mkdir,mkdtemp,writeFile,readFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import net from 'node:net';
const project=resolve('.'),output=resolve('output/account-balances');await mkdir(output,{recursive:true});
await mkdir(resolve('.runtime/test-account-ui'),{recursive:true});
const root=await mkdtemp(resolve('.runtime/test-account-ui/run-'));
const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
const base='http://127.0.0.1:'+port,errors=[],steps=[];let service,desktop,page;
const env={...process.env,PORT:String(port),WUJIAN_WORKBENCH_DB:join(root,'business.sqlite'),WUJIAN_BUNDLE_ROOT:resolve('../资料包'),WUJIAN_OPERATION_DIR:join(root,'操作记录'),WUJIAN_MONITOR_DB:join(root,'monitor.sqlite'),WUJIAN_MONITOR_HOME:join(root,'monitor'),WUJIAN_DESKTOP_PORT:String(port),WUJIAN_DESKTOP_PROFILE:join(root,'profile')};
for(const key of Object.keys(env))if(/TQ_|FEISHU_|DEEPSEEK_|OPENAI_|VOLC_|ARK_/.test(key)||key==='ELECTRON_RUN_AS_NODE')delete env[key];
let logs='';
const { _electron,chromium }=await import(pathToFileURL('C:/Users/86199/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs').href);
const api=async(path,method='GET',input)=>{const response=await fetch(base+path,{method,headers:{Origin:base,'Content-Type':'application/json'},...(input===undefined?{}:{body:JSON.stringify(input)})});const value=await response.json();if(!response.ok)throw Error(JSON.stringify(value));return value};
const accounts=()=>api('/api/workbench/accounts');
async function start(){
 service=spawn(process.execPath,[join(project,'server.mjs')],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
 service.stdout.on('data',x=>logs+=x);service.stderr.on('data',x=>logs+=x);
 for(let i=0;i<100;i++){try{await api('/api/health');break}catch{await new Promise(r=>setTimeout(r,200));if(i===99)throw Error('服务启动超时 '+logs)}}
 desktop=await _electron.launch({executablePath:join(project,'.runtime/desktop-build/小木-win32-x64/小木.exe'),args:[],env,timeout:30000});
 page=await desktop.firstWindow();page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
 await page.waitForSelector('#accountSelect option',{state:'attached'});
}
async function stop(){if(desktop){await desktop.close();desktop=null}if(service){const p=service;service=null;p.kill();await new Promise(r=>p.once('exit',r));}}
const dialog=()=>page.locator('#accountDialog');
async function add(name,initial,balance){
 await page.locator('#addAccount').click();await dialog().locator('[name=alias]').fill(name);await dialog().locator('[name=initialCapital]').fill(String(initial));await dialog().locator('[name=balance]').fill(String(balance));await dialog().locator('[name=note]').fill('隔离验收，不属于真实账户余额');
 await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});await page.waitForFunction(name=>document.querySelector('#accountSelect')?.selectedOptions[0]?.textContent===name,name);
 return (await accounts()).find(a=>a.alias===name);
}
async function view(name){await page.locator('#mainNav [data-view="'+name+'"]').click();await page.waitForSelector('.balance-panel')}
async function sync(value){await page.locator('#content [data-account-action=sync]').click();await dialog().locator('[name=balance]').fill(String(value));await dialog().locator('[name=note]').fill('测试余额同步');await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});await page.waitForFunction(v=>document.querySelector('#accountSummary')?.textContent.includes(v),Number(value).toLocaleString('zh-CN'))}
try{
 await start();const defaults=(await accounts()).filter(a=>a.isDefault);assert.ok(defaults.length);
 const a=await add('数字集团合作账户',1000000,1100000),b=await add('大秦帝国崛起账户',500000,520000);
 steps.push('APP表单创建两账户，名称、初始资金、实际余额已保存');
 await page.locator('#accountSelect').selectOption(a.id);await page.waitForFunction(()=>document.querySelector('#accountSummary').textContent.includes('1,100,000'));
 const card=await api('/api/workbench/cards','POST',{accountId:a.id,symbol:'SH',name:'烧碱',contract:'SH2611',direction:'short'});await page.reload();await page.waitForSelector('#accountSelect option',{state:'attached'});
 await view('metal');await page.waitForSelector('#metalForm');await page.locator('[name=entryNumber]').fill('1200');await page.locator('[name=stopNumber]').fill('1240');
 await sync(1110000);assert.equal(await page.locator('[name=entryNumber]').inputValue(),'1200');assert.equal(await page.locator('[name=accountEquityNumber]').inputValue(),'1110000');
 await view('wood');await page.waitForFunction(()=>document.querySelector('.balance-history')?.textContent.includes('10,000.00'));
 assert.ok((await page.locator('.balance-history').innerText()).includes('金·冻结计划'));await sync(1080000);
 await page.waitForFunction(()=>document.querySelector('.balance-history')?.textContent.includes('-30,000.00'));
 await view('metal');assert.equal(await page.locator('[name=accountEquityNumber]').inputValue(),'1080000');
 steps.push('金110万→111万、木111万→108万，页面互通，未提交入场价保持不变');
 await page.locator('#accountSelect').selectOption(b.id);await page.waitForFunction(()=>!document.querySelector('#metalForm'));assert.ok(!(await page.locator('#content').innerText()).includes('SH2611'));assert.ok((await page.locator('#accountSummary').innerText()).includes('520,000'));
 await page.locator('#accountSelect').selectOption(a.id);await page.waitForSelector('#metalForm');await view('wood');await sync(9999999);
 await page.waitForFunction(()=>document.querySelector('.balance-history')?.textContent.includes('9,999,999.00'));
 await page.locator('[data-balance-correct]').first().click();await dialog().locator('[name=balance]').fill('1090000');await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});
 await page.waitForFunction(()=>document.querySelector('.balance-history')?.textContent.includes('1,090,000.00'));
 await page.locator('[data-balance-void]').first().click();await dialog().locator('[name=reason]').fill('验收错误记录');await dialog().locator('[type=checkbox]').check();await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});
 await page.waitForFunction(()=>document.querySelector('#accountSummary').textContent.includes('1,080,000'));
 await page.locator('[data-balance-note]').first().click();await dialog().locator('[name=note]').fill('错误记录已核对，留痕');await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});
 steps.push('错误余额可在页面修正，再作废恢复108万；备注和历史审计保留');
 for(const width of [1500,1100]){await desktop.evaluate(({BrowserWindow},width)=>BrowserWindow.getAllWindows()[0].setSize(width,980),width);await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:join(output,'wood-'+width+'.png')});}
 await page.goto(base+'/cockpit.html');await page.waitForFunction(()=>document.querySelector('#accountSummary')?.textContent.includes('1,080,000'));await page.locator('[data-account-action=sync]').click();await dialog().locator('[name=balance]').fill('1080000');await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});await page.screenshot({path:join(output,'cockpit.png')});
 await page.goto(base+'/?view=wood');await page.waitForSelector('.balance-history');assert.ok((await page.locator('.balance-history').innerText()).includes('全息版顶部'));
 const before=await accounts();await stop();await start();await page.waitForFunction(()=>document.querySelector('#accountSummary')?.textContent.includes('1,080,000'));assert.deepEqual(await accounts(),before);
 steps.push('重建后的Windows APP关闭并重启，两个账户和108万元余额保持；全息版共用同步接口');
 await page.locator('#accountSelect').selectOption(defaults[0].id);await page.waitForFunction(()=>document.querySelector('#removeAccount').disabled);await page.locator('#accountSelect').selectOption(a.id);await page.waitForFunction(()=>!document.querySelector('#removeAccount').disabled);
 await page.locator('#removeAccount').click();await dialog().locator('[type=checkbox]').check();await dialog().locator('[type=submit]').click();await dialog().waitFor({state:'hidden'});assert.equal((await accounts()).find(x=>x.id===a.id).status,'disabled');assert.equal((await api('/api/workbench/cards/'+card.id)).accountId,a.id);
 steps.push('默认账户删除按钮禁用；有交易卡账户只能停用，交易卡不丢失');
 // Same-origin windows share account selection and balance changes immediately.
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 const context=await browser.newContext({viewport:{width:1500,height:980}}),stable=await context.newPage(),cockpit=await context.newPage();
 await stable.goto(base+'/?view=wood');await stable.waitForSelector('.balance-panel');await cockpit.goto(base+'/cockpit.html');await cockpit.waitForSelector('#accountSelect option',{state:'attached'});
 await stable.locator('#accountSelect').selectOption(b.id);await cockpit.waitForFunction(id=>document.querySelector('#accountSelect')?.value===id,b.id);
 await stable.locator('#syncAccount').click();await stable.locator('#accountDialog [name=balance]').fill('530000');await stable.locator('#accountDialog [type=submit]').click();await cockpit.waitForFunction(()=>document.querySelector('#accountSummary')?.textContent.includes('530,000'));
 await stable.setViewportSize({width:390,height:844});assert.equal(await stable.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await stable.screenshot({path:join(output,'wood-mobile.png'),fullPage:true});steps.push('两窗口同步账户与余额；390宽稳定版无横向溢出');
 }finally{await browser.close()}
 assert.deepEqual(errors,[]);
 await writeFile(join(output,'acceptance.json'),JSON.stringify({passed:true,at:new Date().toISOString(),database:env.WUJIAN_WORKBENCH_DB,steps,errors},null,2));console.log(JSON.stringify({passed:true,steps,output}));
}catch(error){await page?.screenshot({path:join(output,'failure.png')}).catch(()=>{});await writeFile(join(output,'failure.txt'),error.stack);throw error}
finally{await stop();await writeFile(join(output,'server.log'),logs)}
