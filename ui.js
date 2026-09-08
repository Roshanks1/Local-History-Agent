'use strict';
const $ = id => document.getElementById(id);
let session = null, token = null, conversations = [], pendingArchive = null;
let previewSequence = 0;

function element(tag, text, cls) {
 const value=document.createElement(tag); value.textContent=text;
 if(cls)value.className=cls; return value;
}
function busy(value) {
 for(const control of document.querySelectorAll('button,textarea,select'))control.disabled=value;
 $('conversation-search').disabled=value;
}
async function request(data) {
 const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({session,...data})});
 const body=await response.json();
 if(!response.ok)throw Error(body.error || 'Request failed');
 if('session' in body){
  session=body.session;
  if(session)sessionStorage.setItem('history-conversation',session);
  else sessionStorage.removeItem('history-conversation');
 }
 return body;
}
function sourceSection(source) {
 return [source.section,source.subsection].filter(Boolean).join(' / ') || 'Article overview';
}
function previewElement(source,id) {
 const preview=element('span','','citation-preview'); preview.id=id; preview.setAttribute('role','tooltip');
 preview.append(element('strong',source.article_title || source.article_path.replaceAll('_',' ')),element('span',sourceSection(source),'citation-preview-section'));
 preview.append(element('span',source.preview_excerpt || 'Supporting excerpt unavailable for this saved answer.','citation-preview-excerpt'));
 return preview;
}
function closePreviews(except=null) {
 for(const wrap of document.querySelectorAll('.citation-wrap')){
  if(wrap===except)continue;
  wrap.classList.remove('preview-open'); wrap.classList.add('preview-dismissed');
  const button=wrap.querySelector('.citation-preview-toggle'); if(button)button.setAttribute('aria-expanded','false');
 }
}
function positionPreview(wrap) {
 const preview=wrap.querySelector('.citation-preview');
 requestAnimationFrame(()=>{
  wrap.classList.remove('preview-below'); preview.style.transform='';
  const scrollBounds=$('chat-scroll').getBoundingClientRect(), wrapBounds=wrap.getBoundingClientRect();
  const needed=preview.offsetHeight+12, above=wrapBounds.top-scrollBounds.top, below=scrollBounds.bottom-wrapBounds.bottom;
  wrap.classList.toggle('preview-below',above<needed && below>above);
  const bounds=preview.getBoundingClientRect(); let shift=0;
  if(bounds.right>window.innerWidth-12)shift=window.innerWidth-12-bounds.right;
  if(bounds.left+shift<12)shift+=12-(bounds.left+shift);
  if(shift)preview.style.transform=`translateX(${Math.round(shift)}px)`;
 });
}
function activateSource(card,label) {
 for(const control of card.querySelectorAll('[data-source-label]')){
  const active=control.dataset.sourceLabel===label;
  control.classList.toggle('source-active',active);
  if(active)control.setAttribute('aria-current','true'); else control.removeAttribute('aria-current');
 }
}
function sourceLink(source,text,cls) {
 const link=element(source.article_url?'a':'div',text,cls);
 link.dataset.sourceLabel=source.label;
 if(source.article_url){
  link.href=source.article_url; link.target='_blank'; link.rel='noopener noreferrer';
  link.addEventListener('click',()=>activateSource(link.closest('article'),source.label));
 }
 return link;
}
function answerElement(result) {
 const container=element('div','','answer');
 const sourceByLabel=new Map((result.sources || []).map(source=>[source.label,source]));
 let position=0;
 for(const match of result.answer.matchAll(/\[S\d+\]/g)){
  container.append(document.createTextNode(result.answer.slice(position,match.index)));
  const label=match[0].slice(1,-1), source=sourceByLabel.get(label);
  if(source?.article_url){
   const wrap=element('span','','citation-wrap');
   const previewId=`citation-preview-${++previewSequence}`;
   const link=sourceLink(source,match[0],'inline-citation');
   link.title=`Open evidence from ${source.article_title}`; link.setAttribute('aria-describedby',previewId);
   const toggle=element('button','i','citation-preview-toggle'); toggle.type='button';
   toggle.setAttribute('aria-label',`Preview source ${label}`); toggle.setAttribute('aria-controls',previewId); toggle.setAttribute('aria-expanded','false');
   toggle.addEventListener('click',event=>{
    event.preventDefault(); event.stopPropagation(); const opening=!wrap.classList.contains('preview-open');
    closePreviews(wrap); wrap.classList.toggle('preview-dismissed',!opening); wrap.classList.toggle('preview-open',opening); toggle.setAttribute('aria-expanded',String(opening));
    if(opening)positionPreview(wrap);
   });
   wrap.addEventListener('mouseenter',()=>{wrap.classList.remove('preview-dismissed');positionPreview(wrap);});
   wrap.addEventListener('focusin',()=>{wrap.classList.remove('preview-dismissed');positionPreview(wrap);});
   wrap.addEventListener('focusout',()=>setTimeout(()=>{if(!wrap.contains(document.activeElement)){wrap.classList.remove('preview-open');toggle.setAttribute('aria-expanded','false');}},0));
   wrap.append(link,toggle,previewElement(source,previewId)); container.append(wrap);
  }else container.append(document.createTextNode(match[0]));
  position=match.index+match[0].length;
 }
 container.append(document.createTextNode(result.answer.slice(position)));
 return container;
}
function display(question,result,scroll=true) {
 const hadMessages=$('conversation').querySelector('article');
 $('welcome')?.remove();
 const scrollPane=$('chat-scroll');
 const wasNearLatest=!hadMessages || scrollPane.scrollHeight-scrollPane.scrollTop-scrollPane.clientHeight<80;
 const card=element('article','');
 card.append(element('h2',question),answerElement(result));
 const usage=result.usage;
 if(usage)card.append(element('p',usage.skipped?'Generation skipped; no final model call.':`${usage.model} · Context window: ${usage.context_window} tokens · Prompt: ${usage.prompt_tokens ?? 'unavailable'} · Output: ${usage.output_tokens ?? 'unavailable'} · Total: ${usage.total_tokens ?? 'unavailable'}`,'usage'));
 if(result.done_reason==='length')card.append(element('p','Answer reached the output limit and may be incomplete.'));
 const sources=element('div','','sources');
 for(const source of result.sources){
  const link=sourceLink(source,`[${source.label}] ${source.article_title || source.article_path.replaceAll('_',' ')}`,'source');
  const destination=source.evidence_status==='exact'?'Read highlighted evidence ↗':source.evidence_status==='section'?'Exact passage unavailable; showing cited section ↗':source.evidence_status==='article'?'Exact passage unavailable; showing article ↗':'Article unavailable in archive';
  link.append(element('small',sourceSection(source)),element('span',source.preview_excerpt || 'Supporting excerpt unavailable for this saved answer.','source-excerpt'),element('small',destination,'source-destination'));
  sources.append(link);
 }
 card.append(sources);
 if(result.retrieval_debug || result.generation_debug){
  const detail=element('details','');
  detail.append(element('summary','Debug trace'),element('pre',JSON.stringify({retrieval:result.retrieval_debug,generation:result.generation_debug},null,2)));
  card.append(detail);
 }
 $('conversation').append(card);
 if(scroll && wasNearLatest)card.scrollIntoView({behavior:'smooth',block:'start'});
}
function relativeDate(timestamp) {
 const date=new Date(timestamp*1000), now=new Date();
 const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
 const day=new Date(date.getFullYear(),date.getMonth(),date.getDate());
 const difference=Math.round((today-day)/86400000);
 if(difference===0)return 'Today';
 if(difference===1)return 'Yesterday';
 return date.toLocaleDateString(undefined,{month:'short',day:'numeric'});
}
function renderSaved() {
 const query=$('conversation-search').value.trim().toLocaleLowerCase();
 const matches=conversations.filter(item=>item.title.toLocaleLowerCase().includes(query));
 $('saved').replaceChildren();
 for(const item of matches){
  const row=element('div','',`conversation-row${item.id===session?' selected':''}`);
  const open=element('button','','conversation-open'); open.type='button'; open.dataset.action='open'; open.dataset.id=item.id;
  open.append(element('span',item.title,'conversation-title'),element('time',relativeDate(item.updated),'conversation-date'));
  const actions=element('div','','conversation-actions');
  for(const [action,label,title] of [['rename','✎','Rename'],['export','⇩','Export Markdown'],['archive','×','Archive']]){
   const button=element('button',label,'icon-button'); button.type='button'; button.dataset.action=action; button.dataset.id=item.id; button.title=title; button.setAttribute('aria-label',`${title} ${item.title}`); actions.append(button);
  }
  row.append(open,actions); $('saved').append(row);
 }
 $('no-saved').hidden=matches.length>0;
}
async function refreshSaved() {
 const data=await request({action:'list'}); conversations=data.conversations; renderSaved();
}
async function openSaved(id) {
 const data=await request({action:'open',session:id});
 $('conversation').replaceChildren();
 $('chat-scroll').scrollTop=0;
 for(const turn of data.turns)display(turn.question,turn.result,false);
 $('question').value=''; $('status').textContent='Conversation restored. You can continue with a follow-up.'; renderSaved();
}
async function renameSaved(id) {
 const item=conversations.find(value=>value.id===id);
 const title=window.prompt('Rename conversation',item?.title || '');
 if(title===null || title.trim()===item?.title)return;
 await request({action:'rename',session:id,title}); await refreshSaved();
 $('status').textContent='Conversation renamed.';
}
async function exportSaved(id) {
 const data=await request({action:'export',session:id});
 const url=URL.createObjectURL(new Blob([data.markdown],{type:'text/markdown;charset=utf-8'}));
 const link=document.createElement('a'); link.href=url; link.download=data.filename; link.click(); URL.revokeObjectURL(url);
 $('status').textContent='Markdown export created.';
}

$('form').addEventListener('submit',async event=>{
 event.preventDefault(); const question=$('question').value.trim(); if(!question)return;
 busy(true); $('status').textContent='Searching local Wikipedia and preparing an answer…';
 try{
  const data=await request({question,model:$('model').value,debug:$('debug').checked});
  if(data.reset)$('conversation').replaceChildren(); else display(question,data.result);
  $('question').value=''; await refreshSaved(); $('status').textContent=data.reset?'Started a fresh conversation.':'';
 }catch(error){$('status').textContent=error.message;}finally{busy(false);}
});
$('new').addEventListener('click',async()=>{
 busy(true);
 try{await request({new:true});$('conversation').replaceChildren();$('chat-scroll').scrollTop=0;renderSaved();$('status').textContent='Started a fresh conversation. Earlier conversations are saved.';}
 catch(error){$('status').textContent=error.message;}finally{busy(false);}
});
$('conversation-search').addEventListener('input',renderSaved);
$('saved').addEventListener('click',async event=>{
 const button=event.target.closest('button[data-action]'); if(!button)return;
 const {action,id}=button.dataset;
 if(action==='archive'){pendingArchive=id;$('archive-dialog').showModal();return;}
 busy(true);
 try{if(action==='open')await openSaved(id);else if(action==='rename')await renameSaved(id);else if(action==='export')await exportSaved(id);}
 catch(error){$('status').textContent=error.message;}finally{busy(false);}
});
$('archive-dialog').addEventListener('close',async()=>{
 const id=pendingArchive; pendingArchive=null;
 if($('archive-dialog').returnValue!=='confirm' || !id)return;
 busy(true);
 try{
  await request({action:'archive',session:id,confirmed:true});
  if(session===id){session=null;sessionStorage.removeItem('history-conversation');$('conversation').replaceChildren();$('chat-scroll').scrollTop=0;}
  await refreshSaved(); $('status').textContent='Conversation archived.';
 }catch(error){$('status').textContent=error.message;}finally{busy(false);}
});
$('question').addEventListener('keydown',event=>{
 if(event.key!=='Enter' || event.isComposing || event.keyCode===229)return;
 event.preventDefault();
 if(event.metaKey || event.ctrlKey){
  const field=event.target; field.setRangeText('\n',field.selectionStart,field.selectionEnd,'end'); field.dispatchEvent(new Event('input',{bubbles:true}));
 }else if(!event.repeat && !$('send').disabled){$('form').requestSubmit();}
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closePreviews();});
document.addEventListener('click',event=>{if(!event.target.closest('.citation-wrap'))closePreviews();});
$('chat-scroll').addEventListener('scroll',()=>closePreviews(),{passive:true});

busy(true);
fetch('/api/bootstrap').then(response=>{if(!response.ok)throw Error('Cannot connect to local server');return response.json();}).then(async data=>{
 token=data.token;
 const remembered=sessionStorage.getItem('history-conversation');
 if(remembered){try{await openSaved(remembered);}catch(error){sessionStorage.removeItem('history-conversation');$('status').textContent=error.message;}}
 await refreshSaved(); busy(false);
}).catch(error=>{$('status').textContent=error.message+' Reload to retry.';});
