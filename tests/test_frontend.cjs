'use strict';
// Run the real browser controller with deterministic HTTP responses and a tiny DOM.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
  return {value:'', textContent:'', disabled:false, children:[],
    classList:{add(){}, remove(){}, toggle(){}},
    append(...items){this.children.push(...items);},
    replaceChildren(...items){this.children=items;},
    addEventListener(){}, setAttribute(){}};
}
function status(version, job='done', rootId=1) {
  return {root:{id:rootId, path:'D:/fixtures', updated:version},
    roots:[], documents:1, searchable:1, issues:[], issue_count:0,
    job:{state:job, message:job, progress:{}}};
}
function results(count) {
  const doc={id:1,kind:'txt',relative:'needle.txt',matched_pages:[],snippets:[],
    name_segments:[{text:'needle.txt',hit:true}],filename_match:true};
  return {total:count,limit:20,results:count?[doc]:[]};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
async function controller(initialJob='idle') {
  const elements = new Map();
  const get = id => {if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const searches=[];
  let reply=()=>results(1);
  const context=vm.createContext({URLSearchParams,
    document:{getElementById:get,querySelector:()=>({content:'fixture-token'}),
      createElement:element,createTextNode:text=>({textContent:text})},
    clearTimeout(){},setTimeout(){return 1;},
    fetch:async url=>({ok:true,json:async()=>{
      if(url==='/api/status')return status('2026-11-02T00:00:00Z',initialJob);
      assert.ok(url.startsWith('/api/search?'));
      searches.push(url);
      return reply();
    }})});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8')+
    '\nthis.controller={renderStatus,search};',context);
  await settle();
  get('query').value='needle';
  await context.controller.search();
  assert.equal(get('result-count').textContent,'找到 1 份文档');
  return {...context.controller,get,searches,setReply:fn=>{reply=fn;}};
}

test('fast update: first status is done and removed document disappears', async()=>{
  const app=await controller();
  app.setReply(()=>results(0));
  app.renderStatus(status('2026-11-02T00:00:01Z'));
  await settle();
  assert.equal(app.searches.length,2);
  assert.equal(app.get('result-count').textContent,'找到 0 份文档');
  assert.equal(app.get('results').children.length,0);
});

test('consecutive fast updates refresh once each, repeated polls do not', async()=>{
  const app=await controller('done');
  for(const version of ['2026-11-02T00:00:01Z','2026-11-02T00:00:02Z']) {
    app.renderStatus(status(version));
    await settle();
    const calls=app.searches.length;
    app.renderStatus(status(version));
    await settle();
    assert.equal(app.searches.length,calls);
  }
  assert.equal(app.searches.length,3);
});

test('observed running task still refreshes on commit', async()=>{
  const app=await controller();
  app.renderStatus(status('2026-11-02T00:00:00Z','running'));
  assert.equal(app.searches.length,1);
  app.renderStatus(status('2026-11-02T00:00:01Z'));
  await settle();
  assert.equal(app.searches.length,2);
});

test('failed/cancelled jobs, empty query and root switches do not auto-search', async()=>{
  const app=await controller();
  for(const job of ['running','error','cancelled','idle'])
    app.renderStatus(status('2026-11-02T00:00:00Z',job));
  await settle();
  assert.equal(app.searches.length,1);
  app.get('query').value='  ';
  app.renderStatus(status('2026-11-02T00:00:01Z'));
  await settle();
  assert.equal(app.searches.length,1);
  app.get('query').value='needle';
  app.renderStatus(status('2026-11-02T00:00:02Z','done',2));
  await settle();
  assert.equal(app.searches.length,1);
  assert.equal(app.get('results').children.length,0);
});

test('old in-flight search cannot replace the refreshed results', async()=>{
  const app=await controller();
  let resolveOld;
  app.setReply(()=>new Promise(resolve=>{resolveOld=resolve;}));
  const pending=app.search();
  await settle();
  app.setReply(()=>results(0));
  app.renderStatus(status('2026-11-02T00:00:01Z'));
  await settle();
  resolveOld(results(1));
  await pending;
  assert.equal(app.get('result-count').textContent,'找到 0 份文档');
});
