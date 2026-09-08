'use strict';
const $ = id => document.getElementById(id);
let session = null, token = null;
function element(tag, text, cls) { const e=document.createElement(tag); e.textContent=text; if(cls)e.className=cls; return e; }
function busy(value) { for(const id of ['send','new','question','model','debug','saved']) $(id).disabled=value; }
async function request(data) {
 const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({session,...data})});
 const body=await response.json(); if(!response.ok)throw Error(body.error || 'Request failed'); if('session' in body){session=body.session;if(session)sessionStorage.setItem('history-conversation',session);else sessionStorage.removeItem('history-conversation');} return body;
}
function display(question,result,scroll=true) {
 $('welcome')?.remove(); const card=element('article',''); card.append(element('h2',question),element('div',result.answer,'answer'));
 const u=result.usage; if(u)card.append(element('p',u.skipped?'Generation skipped; no final model call.':`${u.model} · Context window: ${u.context_window} tokens · Prompt: ${u.prompt_tokens ?? 'unavailable'} · Output: ${u.output_tokens ?? 'unavailable'} · Total: ${u.total_tokens ?? 'unavailable'}`,'usage'));
 if(result.done_reason==='length')card.append(element('p','Answer reached the output limit and may be incomplete.'));
 const sources=element('div','','sources'); for(const s of result.sources){const link=element(s.article_url?'a':'div',`[${s.label}] ${s.article_path.replaceAll('_',' ')}`,'source');if(s.article_url){link.href=s.article_url;link.target='_blank';link.rel='noopener noreferrer';}link.append(element('small',s.section+(s.subsection?' / '+s.subsection:'')),element('small',s.article_url?(s.article_url.includes('#')?'Read source section ↗':'Read complete offline article ↗'):'Article unavailable in archive'));sources.append(link);}card.append(sources);
 if(result.retrieval_debug || result.generation_debug){const detail=element('details','');detail.append(element('summary','Debug trace'),element('pre',JSON.stringify({retrieval:result.retrieval_debug,generation:result.generation_debug},null,2)));card.append(detail);} $('conversation').append(card);if(scroll)card.scrollIntoView({behavior:'smooth',block:'start'});
}
$('form').addEventListener('submit',async event=>{event.preventDefault();const question=$('question').value.trim();if(!question)return;busy(true);$('status').textContent='Searching local Wikipedia and preparing an answer…';try{const data=await request({question,model:$('model').value,debug:$('debug').checked});if(data.reset)$('conversation').replaceChildren();else display(question,data.result);$('question').value='';await refreshSaved();$('status').textContent=data.reset?'Started a fresh conversation.':'';}catch(e){$('status').textContent=e.message;}finally{busy(false);}});
$('new').addEventListener('click',async()=>{busy(true);try{await request({new:true});$('conversation').replaceChildren();$('saved').value='';$('status').textContent='Started a fresh conversation. Earlier conversations are saved.';}catch(e){$('status').textContent=e.message;}finally{busy(false);}});
async function refreshSaved() {
 const data=await request({action:'list'});
 $('saved').replaceChildren(new Option('Choose a saved conversation…',''));
 for(const c of data.conversations) $('saved').append(new Option(c.title,c.id));
 $('saved').value=session || '';
}
async function openSaved(id) {
 const data=await request({action:'open',session:id});
 $('conversation').replaceChildren();
 for(const turn of data.turns)display(turn.question,turn.result,false);
 $('question').value='';$('status').textContent='Conversation restored. You can continue with a follow-up.';
}
$('saved').addEventListener('change',async()=>{
 const id=$('saved').value;if(!id)return;busy(true);
 try{await openSaved(id);}catch(e){$('status').textContent=e.message;$('saved').value=session || '';}
 finally{busy(false);}
});
$('question').addEventListener('keydown',event=>{
 if(event.key!=='Enter' || event.isComposing || event.keyCode===229)return;
 event.preventDefault();
 if(event.metaKey || event.ctrlKey){
  const field=event.target;
  field.setRangeText('\n',field.selectionStart,field.selectionEnd,'end');
  field.dispatchEvent(new Event('input',{bubbles:true}));
 }else if(!event.repeat && !$('send').disabled){$('form').requestSubmit();}
});
busy(true);fetch('/api/bootstrap').then(r=>{if(!r.ok)throw Error('Cannot connect to local server');return r.json();}).then(async data=>{
 token=data.token;
 const remembered=sessionStorage.getItem('history-conversation');
 if(remembered){try{await openSaved(remembered);}catch(e){sessionStorage.removeItem('history-conversation');$('status').textContent=e.message;}}
 await refreshSaved();busy(false);
}).catch(e=>{$('status').textContent=e.message+' Reload to retry.';});
