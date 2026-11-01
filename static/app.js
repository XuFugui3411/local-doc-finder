'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="local-token"]').content;
const state = {root:null, kind:'all', offset:0, total:0, limit:20, sequence:0, busy:false, picking:false, timer:null};
async function api(path, body, signal) {
  const response = await fetch(path, {method:body===undefined?'GET':'POST', headers:{'X-Local-Token':token,...(body===undefined?{}:{'Content-Type':'application/json'})}, body:body===undefined?undefined:JSON.stringify(body), signal});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '本地服务暂时不可用');
  return data;
}
function notice(message='') { $('notice').textContent=message; $('notice').classList.toggle('hidden',!message); }
function empty(title,text) { $('empty-title').textContent=title; $('empty-text').textContent=text; $('empty').classList.remove('hidden'); }
function clearResults() { state.sequence++; $('search-button').disabled=false; $('results').replaceChildren(); $('pagination').classList.add('hidden'); $('result-count').textContent='等待搜索'; }
function highlights(parent, parts) { for (const part of parts) { const el=document.createElement(part.hit?'mark':'span'); el.textContent=part.text; parent.append(el); } }
function node(tag,cls,text) { const el=document.createElement(tag); if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el; }
function link(doc,page,block,location) { const label=doc.kind==='docx'?(location?`查看${location} ↗`:'查看提取文本 ↗'):(page?`查看第 ${page} 页 ↗`:'打开原文 ↗');const a=node('a','',label);a.href=`/document?id=${doc.id}${doc.kind==='docx'&&block?'#block-'+block:page?'#page='+page:''}`;a.target='_blank';a.rel='noopener';return a; }
function renderResults(data) {
  state.total=data.total;state.limit=data.limit;
  $('results').replaceChildren();$('empty').classList.add('hidden');
  $('result-count').textContent=`找到 ${data.total} 份文档`;
  for (const doc of data.results) {
    const card=node('article','result card'), head=node('div','result-head'), identity=node('div','file-identity');
    identity.append(node('span','file-badge',doc.kind.toUpperCase()));
    const info=node('div'), title=link(doc,doc.matched_pages[0],doc.snippets[0]?.block);title.className='result-title';title.replaceChildren();highlights(title,doc.name_segments);
    info.append(title,node('div','relative',doc.relative));identity.append(info);head.append(identity);
    const open=link(doc,doc.matched_pages[0],doc.snippets[0]?.block);open.className='open-link';head.append(open);card.append(head);
    const labels=[];if(doc.filename_match)labels.push('文件名命中');if(doc.snippets.length)labels.push('正文命中');if(doc.matched_pages.length)labels.push(`PDF 第 ${doc.matched_pages.join('、')} 页`);
    card.append(node('p','hit-note',labels.join(' · ')));
    if(doc.kind==='docx')card.append(node('p','hit-note','DOCX 按段落 / 表格行定位，不标固定页码'));
    for (const excerpt of doc.snippets) {
      const quote=node('blockquote','snippet');
      if(excerpt.page||excerpt.block){const badge=link(doc,excerpt.page,excerpt.block,excerpt.location);badge.className='snippet-label';quote.append(badge);}
      if(excerpt.prefix)quote.append(document.createTextNode('…'));
      highlights(quote,excerpt.segments);
      if(excerpt.suffix)quote.append(document.createTextNode('…'));
      card.append(quote);
    }
    if(!doc.snippets.length)card.append(node('p','no-excerpt','本次仅命中文件名，没有匹配的正文上下文。'));
    if(doc.message)card.append(node('div','warning',doc.message));
    $('results').append(card);
  }
  if(!data.results.length)empty('没有找到匹配文档','试试更短的关键词，或在新增、修改、删除资料后更新索引。多个词需要全部匹配。');
  $('pagination').classList.toggle('hidden',data.total<=data.limit);
  $('previous').disabled=state.offset===0;$('next').disabled=state.offset+data.limit>=data.total;
  $('page-label').textContent=`第 ${Math.floor(state.offset/data.limit)+1} / ${Math.max(1,Math.ceil(data.total/data.limit))} 页`;
}
async function search(reset=true) {
  if(reset)state.offset=0;
  notice();
  const query=$('query').value.trim();
  if(!query){clearResults();empty('输入你记得的关键词','可以搜索文件名或正文；例如输入“项目 预算”，查找同时包含这两个词的资料。');return;}
  if(!state.root){notice('请先选择资料目录并更新索引。');return;}
  const sequence=++state.sequence;$('result-count').textContent='正在检索…';$('search-button').disabled=true;
  try { const result=await api('/api/search?'+new URLSearchParams({q:query,kind:state.kind,offset:state.offset}));if(sequence===state.sequence)renderResults(result); }
  catch(error){if(sequence===state.sequence){notice(error.message);$('result-count').textContent='搜索未完成';}}
  finally{if(sequence===state.sequence)$('search-button').disabled=false;}
}
function renderStatus(data) {
  const changed=state.root?.id!==data.root?.id;
  // A fast update may finish between polls; observe the committed index version.
  const indexChanged=!changed&&state.root?.updated!==data.root?.updated;
  state.root=data.root;state.busy=data.job.state==='running';
  if(changed){clearResults();$('folder').value=data.root?.path||'';empty(data.documents?'索引已经准备好':'先为资料建立一份索引',data.documents?'输入关键词，搜索文件名和正文中的原话。':'选择目录并点击「建立 / 更新索引」，再输入记得的关键词。');}
  if(!data.root&&!$('folder').value)$('folder').value='';
  $('doc-count').textContent=data.root?data.documents:'—';$('text-count').textContent=data.root?data.searchable:'—';$('issue-count').textContent=data.root?(data.issue_count||0):'—';
  $('updated').textContent=data.root?.updated?'上次更新 '+new Date(data.root.updated).toLocaleString('zh-CN',{hour12:false}):'尚未建立索引';
  for(const id of ['folder','browse','use-folder','history','update'])$(id).disabled=state.busy||state.picking;
  $('cancel').classList.toggle('hidden',!state.busy);
  $('history').replaceChildren();
  if(!data.roots.length){const option=node('option','','尚未选择目录');option.value='';$('history').append(option);}
  for(const root of data.roots){const option=node('option','',root.path);option.value=root.path;option.selected=root.id===data.root?.id;$('history').append(option);}
  const job=data.job,p=job.progress;
  $('job-box').classList.toggle('hidden',job.state==='idle');$('job-box').classList.toggle('finished',!state.busy);
  $('job-title').textContent=job.message;
  $('job-detail').textContent=job.state==='running'?`已处理 ${p.added||0} 个新增、${p.modified||0} 个修改，${p.unchanged||0} 个未变化${p.current?' · 当前：'+p.current:''}`:job.state==='done'?`新增 ${p.added} · 修改 ${p.modified} · 未变 ${p.unchanged} · 删除 ${p.deleted} · 失败 ${p.failed} · 跳过 ${p.skipped}`:'原索引未替换，可处理问题后重试。';
  $('issues-panel').classList.toggle('hidden',!data.issues?.length);
  $('issues-title').textContent=`读取与提取提示 · ${data.issue_count||0} 项${data.issue_count>500?'（显示前 500 项）':''}`;
  $('issues').replaceChildren();for(const issue of data.issues||[]){const li=node('li');li.append(node('b','',issue.relative),document.createTextNode(issue.message));$('issues').append(li);}
  if(indexChanged&&data.root?.updated&&$('query').value.trim())search();
  if(!$('query').value.trim()&&data.root?.updated&&!state.busy)empty(data.documents?'索引已经准备好':'目录中没有支持的文档',data.documents?'输入记得的关键词，查找文件名和正文；读取或提取提示见下方。':'支持 .md、.markdown、.txt、.docx 和有文本层的 .pdf；请检查目录或查看下方提示。');
}
async function refresh(){clearTimeout(state.timer);try{renderStatus(await api('/api/status'));}catch(error){notice('无法连接本地服务：'+error.message);}state.timer=setTimeout(refresh,state.busy?850:3500);}
async function choose(path){const data=await api('/api/root',{path});renderStatus(data);$('folder').value=data.root.path;notice();}
$('use-folder').addEventListener('click',async()=>{try{await choose($('folder').value.trim());}catch(error){notice(error.message);}});
$('folder').addEventListener('keydown',event=>{if(event.key==='Enter')$('use-folder').click();});
$('history').addEventListener('change',async event=>{if(event.target.value)try{await choose(event.target.value);}catch(error){notice(error.message);}});
$('browse').addEventListener('click',async()=>{if(state.picking)return;state.picking=true;const button=$('browse');button.disabled=true;button.textContent='正在选择…';try{const result=await api('/api/pick',{});if(result.path)await choose(result.path);}catch(error){notice('目录选择未完成，可直接粘贴路径：'+error.message);}finally{state.picking=false;button.textContent='选择目录…';refresh();}});
$('update').addEventListener('click',async()=>{try{if(!state.root||$('folder').value.trim()!==state.root.path)await choose($('folder').value.trim());await api('/api/update',{});await refresh();}catch(error){notice(error.message);}});
$('cancel').addEventListener('click',async()=>{try{await api('/api/cancel',{});notice('已请求取消；当前 PDF 提取可能需要最多 30 秒退出，未提交的更新会回滚。');}catch(error){notice(error.message);}});
$('search-form').addEventListener('submit',event=>{event.preventDefault();search();});
$('filters').addEventListener('click',event=>{const button=event.target.closest('button[data-kind]');if(!button)return;state.kind=button.dataset.kind;for(const child of $('filters').children){child.classList.toggle('active',child===button);child.setAttribute('aria-pressed',String(child===button));}if($('query').value.trim())search();});
$('previous').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);search(false);});
$('next').addEventListener('click',()=>{state.offset+=state.limit;search(false);});
refresh();
