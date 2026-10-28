import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {databaseManifest} from './system-backup.mjs';

const base='http://127.0.0.1:4318';
const dark=process.argv.includes('--dark'),theme=dark?'dark':'wood';
const out=resolve(`output/playwright/fire-preview-${dark?'dark-':''}2026-10-19`);
const themeBackground=dark?'rgb(17, 19, 20)':'rgb(246, 246, 244)';
await mkdir(out,{recursive:true});
const get=async path=>{const r=await fetch(base+path);assert.ok(r.ok,path);return r.json()};
const protectedFiles=['dist/index.html','dist/workbench.js','dist/workbench.css','dist/fire-display.js','server.mjs','integrations/day-trend.mjs','integrations/five-workbench.mjs','integrations/resonance-rule.mjs'];
const fileHashes=async()=>Object.fromEntries(await Promise.all(protectedFiles.map(async path=>[path,createHash('sha256').update(await readFile(resolve(path))).digest('hex')])));
const before={business:databaseManifest(resolve('.runtime/five-workbench.sqlite')),files:await fileHashes(),fire:await get('/api/workbench/fire'),rules:await get('/api/workbench/rules')};
const {chromium}=await import('file:///C:/Users/86199/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:1500,height:1060}});
const page=await context.newPage(),errors=[],requests=[],sizes=[],modes=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))requests.push({method:r.method(),url:r.url()})});
try{
  await page.goto(base+`/fire-preview${dark?'-dark':''}.html`);
  await page.locator('#previewLoading').waitFor({state:'hidden'});
  const frame=page.frameLocator('#workbenchPreview');
  await frame.locator('.fire-overview [data-fire-detail]').first().waitFor();
  await frame.locator('[data-strength-pair="2"]').waitFor();
  const account=frame.locator('#accountSelect');
  const option=await account.locator('option').allTextContents();
  const chosen=option.find(x=>x.includes('大秦帝国'));
  if(chosen){await account.selectOption({label:chosen});await frame.locator('.fire-overview [data-fire-detail]').first().waitFor()}
  for(const mode of ['month-week-day','month-week','week-day','day-trend']){
    await frame.locator(`[data-mode="${mode}"]`).click();
    const long=await frame.locator('.fire-overview .fire-long [data-fire-detail]').count();
    const short=await frame.locator('.fire-overview .fire-short [data-fire-detail]').count();
    assert.equal(long,before.fire.counts[mode].long);assert.equal(short,before.fire.counts[mode].short);
    modes.push({mode,long,short});
  }
  await frame.locator('[data-mode="month-week-day"]').click();
  await frame.locator('[data-strength-pair="2"]').waitFor();
  assert.equal(await frame.locator('.fire-long .fire-strength-strong').first().evaluate(b=>getComputedStyle(b).backgroundColor),dark?'rgb(50, 36, 37)':'rgb(251, 239, 236)');
  assert.equal(await frame.locator('.fire-short .fire-strength-strong').first().evaluate(b=>getComputedStyle(b).backgroundColor),dark?'rgb(30, 48, 39)':'rgb(237, 244, 239)');
  for(const width of [1920,1500,1100,390]){
    await page.setViewportSize({width,height:width===390?1000:1060});
    const layout=await frame.locator('body').evaluate(body=>({
      width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
      tabs:[...body.querySelectorAll('[data-mode]')].map(b=>({left:b.getBoundingClientRect().left,right:b.getBoundingClientRect().right,client:b.clientWidth,scroll:b.scrollWidth})),
      clipped:[...body.querySelectorAll('.fire-overview button[data-fire-detail]')].filter(b=>b.scrollWidth>b.clientWidth+1||b.scrollHeight>b.clientHeight+1).map(b=>b.textContent)
    }));
    assert.ok(layout.scrollWidth<=layout.width+1,`${width}: horizontal overflow ${layout.scrollWidth}`);
    assert.ok(layout.tabs.every(b=>b.left>=0&&b.right<=layout.width+1&&b.scroll<=b.client+1),`${width}: mode overflow`);
    assert.deepEqual(layout.clipped,[],`${width}: clipped candidates`);
    await page.screenshot({path:resolve(out,`${theme}-${width}.png`),fullPage:false});
    if(width===1500)await frame.locator('body').screenshot({path:resolve(out,`${theme}-full.png`)});
    sizes.push({width,...layout});
  }
  await page.setViewportSize({width:1500,height:1060});
  await page.locator('[data-appearance="original"]').click();
  assert.equal(await frame.locator('body').evaluate(b=>getComputedStyle(b).backgroundColor),'rgb(7, 16, 15)');
  await page.screenshot({path:resolve(out,'original-1500.png')});
  await page.locator(`[data-appearance="${theme}"]`).click();
  assert.equal(await frame.locator('body').evaluate(b=>getComputedStyle(b).backgroundColor),themeBackground);
  await frame.locator('.fire-overview [data-fire-detail]').first().click();
  await frame.locator('#contractChart canvas,#contractChart svg').first().waitFor();
  assert.equal(await frame.locator('#detailResearch').isEnabled(),true);
  await page.screenshot({path:resolve(out,'contract-detail.png')});
  await frame.locator('#modalClose').click();
  await frame.locator('[data-strength-pair="0"]').click();
  await frame.locator('#modal .strength-table').waitFor();
  await page.screenshot({path:resolve(out,'strength-detail.png')});
  await frame.locator('#modalClose').click();
  await frame.locator('#fireFilter').selectOption('all');
  assert.equal(await frame.locator('main > .panel > .table-wrap tbody tr').count(),87);
  await frame.locator('#fireFilter').selectOption('candidate');
  await frame.locator('#mainNav [data-view="water"]').click();
  await frame.locator('#viewTitle').filter({hasText:'分析机会'}).waitFor();
  assert.equal(await frame.locator('body').evaluate(b=>getComputedStyle(b).backgroundColor),'rgb(7, 16, 15)');
  await frame.locator('#mainNav [data-view="fire"]').click();
  await frame.locator('.fire-overview [data-fire-detail]').first().waitFor();
  await page.waitForFunction(expected=>{
    const doc=document.querySelector('#workbenchPreview').contentDocument;
    return doc?.body&&doc.defaultView.getComputedStyle(doc.body).backgroundColor===expected;
  },themeBackground);
  assert.equal(await frame.locator('body').evaluate(b=>getComputedStyle(b).backgroundColor),themeBackground);
  await frame.locator('#ruleVersion').click();
  await frame.locator('.rule-mode-tabs').waitFor();
  await page.screenshot({path:resolve(out,'rule-detail.png')});
  await frame.locator('#modalClose').click();
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[],'预览验收不应写入任何业务接口');
  assert.deepEqual(databaseManifest(resolve('.runtime/five-workbench.sqlite')),before.business);
  assert.deepEqual(await fileHashes(),before.files);
  const afterRules=await get('/api/workbench/rules');
  assert.equal(afterRules.combinedHash,before.rules.combinedHash);assert.equal(afterRules.runId,before.rules.runId);
  assert.deepEqual((await get('/api/workbench/fire')).counts,before.fire.counts);
  await writeFile(resolve(out,'verification.json'),JSON.stringify({passed:true,checkedAt:new Date(Date.now()+28800000).toISOString().replace('Z','+08:00'),dataDate:before.fire.data_date,modes,sizes,errors,mutatingRequests:requests,businessTablesUnchanged:Object.keys(before.business.tables).length,protectedFiles:before.files,ruleHashUnchanged:true,interactions:['四模式切换','原版对比','品种K线详情','三组多强空弱证据','87品种列表','账户切换','其他页面自动恢复原样','规则详情']},null,2));
  console.log(JSON.stringify({passed:true,out,modes,sizes:sizes.map(s=>s.width),errors,businessTablesUnchanged:Object.keys(before.business.tables).length}));
}finally{await browser.close()}
