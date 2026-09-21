"""Browser UI for blind human comparison. Dataset values are rendered as text."""

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>题目质量比较</title><style>
:root{color-scheme:light;--ink:#182e36;--muted:#63777e;--line:#d9e3e5;--accent:#126d72;--paper:#fff}
*{box-sizing:border-box}body{margin:0;background:#f2f5f4;color:var(--ink);font:15px/1.65 system-ui,sans-serif}
main{max-width:1560px;margin:auto;padding:24px 28px 60px}header{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:22px}
h1{font-size:24px;margin:0}h2{font-size:20px;margin:0}h3{font-size:14px;margin:0 0 10px;color:var(--muted)}p{margin:8px 0}
.muted{color:var(--muted);font-size:13px}.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:22px}
.requirement{border-left:4px solid var(--accent);margin-bottom:20px}.text{white-space:pre-wrap;overflow-wrap:anywhere}
.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;align-items:start}.side-head{display:flex;align-items:center;gap:10px;padding-bottom:16px;border-bottom:1px solid var(--line);margin-bottom:18px}
.columns>.card{max-height:72vh;overflow:auto}.side-head{position:sticky;top:0;background:var(--paper);z-index:1}
.badge{background:#e4f2f0;color:var(--accent);padding:2px 12px;border-radius:5px;font-weight:700}
section{margin-bottom:22px}details{border-top:1px solid var(--line);padding:12px 0}summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f7;padding:14px;font:13px/1.65 ui-monospace,monospace;max-height:520px;overflow:auto}
button,input,textarea,select{font:inherit;border:1px solid #b9cbce;border-radius:6px;padding:8px 12px}button{cursor:pointer;background:white;color:var(--ink)}button:hover{border-color:var(--accent)}button:disabled{opacity:.45;cursor:default}
button.primary{background:var(--accent);color:white;border-color:var(--accent)}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.decision{margin-top:20px}.choices{display:flex;gap:16px;margin:16px 0}.choices label{flex:1;cursor:pointer;border:1px solid var(--line);border-radius:7px;padding:14px}.choices label:has(input:checked){background:#e4f2f0;border-color:var(--accent)}
textarea{display:block;width:100%;min-height:78px;margin:8px 0 14px;resize:vertical}input[type=radio]{accent-color:var(--accent)}
#error{color:#9e302d;background:#fff0eb;padding:12px;border-radius:6px;white-space:pre-wrap}#login{max-width:620px;margin:70px auto}#restore{width:100%;margin:8px 0 12px}
.artifact{margin:10px 0;padding:10px;background:#f5f7f7;border-radius:5px}.artifact a{color:var(--accent)}.artifact img{display:block;max-width:100%;max-height:600px;margin-top:10px}
#session-code{overflow-wrap:anywhere}#account{margin:0;font-size:12px;max-width:380px}#progress{font-variant-numeric:tabular-nums}.field{margin:12px 0}.field>strong{font-size:13px;color:var(--muted)}
[hidden]{display:none!important}@media(max-width:850px){main{padding:16px 12px}.columns{grid-template-columns:1fr}header{align-items:start;flex-direction:column}.card{padding:16px}}
</style></head><body><main>
<header><div><div class="muted">人工评审 · 双题盲评</div><h1 id="title">题目质量比较</h1></div><details id="account" hidden><summary>恢复进度 / 退出</summary><p>保存此恢复码，可以在另一浏览器继续。请勿与其他评审人共用。</p><code id="session-code"></code><p><button id="logout">退出当前评审</button></p></details></header>
<p id="error" role="alert" hidden></p>
<div id="login" class="card"><h2>哪道题更适合评估给定需求？</h2><p>请综合考虑需求契合度和评测质量，比较题目内容、可解性、评分合理性及模型作答所提供的证据。模型得分更低不等于题目更好。</p><p class="muted">每组只能选择 A 或 B。左右位置已随机安排；未提交的组不计入结果。</p><button id="start" class="primary">开始新的评审</button><hr><label for="restore">继续已有评审</label><input id="restore" autocomplete="off" placeholder="粘贴恢复码"><button id="resume">恢复进度</button></div>
<div id="review" hidden>
<div class="toolbar" style="margin-bottom:16px"><strong id="progress"></strong><select id="jump" aria-label="选择比较组"></select><span class="muted">按需求契合度和评测质量综合选择</span></div>
<div class="card requirement"><h3>用户测评需求</h3><div id="requirement" class="text math"></div></div>
<div class="columns"><article id="side-a" class="card"></article><article id="side-b" class="card"></article></div>
<form id="vote" class="card decision"><h2>哪道题更好？</h2><p class="muted">请选择更适合评估上述用户需求的一道题。答案与作答仅作为判断题目质量的证据。</p>
<div class="choices"><label><input type="radio" name="choice" value="A" required> A 更好</label><label><input type="radio" name="choice" value="B" required> B 更好</label></div>
<label for="reason">理由（可选）</label><textarea id="reason" placeholder="哪些具体内容影响了你的判断？"></textarea>
<div class="toolbar"><button id="previous" type="button">上一组</button><button id="save" class="primary" type="submit">提交并继续</button><button id="next" type="button">下一组</button><span id="saved" class="muted" role="status"></span></div>
</form></div></main><script>
const $=id=>document.getElementById(id);
let token='', overview=null, position=0, dirty=false, busy=false;
const storageKey='evalclaw-human-review:'+location.pathname;
const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const labels={title:'标题',model:'作答模型',final_response:'最终作答',execution_error:'执行错误',score:'原评分',judge_reasoning:'评分理由',content:'题目内容',messages:'消息',prompt:'题面',choices:'选项',reference_answer:'参考答案',evaluation:'评分规则',environment:'环境',interaction:'交互方式',response:'模型作答',raw_response:'原始作答',events:'交互轨迹',final_messages:'最终回复',outputs:'产物',rubric:'评分标准',system_prompt:'系统提示',task_type:'题型'};
function showError(e){$('error').hidden=false;$('error').textContent=e.message||String(e);}
async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(value.error||'请求失败');return value;}
function math(element){if(window.renderMathInElement)renderMathInElement(element,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false},{left:'$',right:'$',display:false}],throwOnError:false,strict:false,trust:false});}
function content(value){
 if(value===null)return make('div','未提供；不代表没有作答或内容不存在。','muted');
 if(typeof value==='string'){const e=make('div',value,'text math');return e;}
 if(Array.isArray(value)){const e=make('div');value.forEach((v,i)=>{const row=make('details');row.append(make('summary','第 '+(i+1)+' 项'));row.addEventListener('toggle',()=>{if(row.open&&!row.dataset.loaded){row.append(content(v));row.dataset.loaded='1';math(row);}});e.append(row);});if(!value.length)e.append(make('div','[]','muted'));return e;}
 if(typeof value==='object'){const e=make('div');for(const [key,v] of Object.entries(value)){const row=make('div',undefined,'field');row.append(make('strong',labels[key]||key));if(typeof v==='string'||v===null||typeof v!=='object')row.append(content(v));else{const details=make('details');details.append(make('summary','展开完整内容'));details.addEventListener('toggle',()=>{if(details.open&&!details.dataset.loaded){details.append(content(v));details.dataset.loaded='1';math(details);}});row.append(details);}e.append(row);}return e;}
 return make('div',String(value),'text');
}
function section(parent,title,value,open){const s=make('details');s.open=open;s.append(make('summary',title));const body=make('div');s.append(body);let loaded=false;const render=()=>{if(s.open&&!loaded){body.append(content(value));loaded=true;math(body);}};s.addEventListener('toggle',render);render();parent.append(s);}
function artifactURL(pair,side,index){return '/api/artifact?'+new URLSearchParams({session:token,pair,side,index});}
function renderSide(node,candidate,side,index){
 node.replaceChildren();const head=make('div',undefined,'side-head');head.append(make('span',side===0?'A':'B','badge'),make('h2','候选题目'));node.append(head);
 section(node,'题目内容（完整）',candidate.task,true);
 for(const s of candidate.sections)section(node,s.title,s.content,false);
 section(node,'模型作答（完整）',candidate.response,true);
 if(candidate.artifacts.length){const group=make('section');group.append(make('h3','附件与执行证据'));
 for(const a of candidate.artifacts){const row=make('div',undefined,'artifact'),url=artifactURL(index,side,a.index);row.append(make('div',a.label+' · '+a.bytes.toLocaleString()+' bytes'));const download=make('a','下载完整文件');download.href=url;download.download=a.label;row.append(download);
 if(a.bytes<=2*1024*1024){const preview=make('button','预览');preview.type='button';preview.style.marginLeft='12px';preview.onclick=async()=>{preview.disabled=true;try{const r=await fetch(url);if(!r.ok)throw Error('附件读取失败');const data=await r.arrayBuffer(),bytes=new Uint8Array(data);const png=bytes[0]===137&&bytes[1]===80&&bytes[2]===78&&bytes[3]===71;const jpg=bytes[0]===255&&bytes[1]===216&&bytes[2]===255;if(png||jpg){const img=make('img');img.alt=a.label;const objectURL=URL.createObjectURL(new Blob([data],{type:png?'image/png':'image/jpeg'}));img.onload=()=>URL.revokeObjectURL(objectURL);img.src=objectURL;row.append(img);}else{try{const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);if(text.includes('\u0000'))throw Error();row.append(make('pre',text));}catch{row.append(make('p','二进制文件，请下载查看。','muted'));}}}catch(e){showError(e);preview.disabled=false;}};row.append(preview);}else row.append(make('p','大文件请下载查看；下载包含完整内容。','muted'));group.append(row);}node.append(group);}
 math(node);
}
function setBusy(value){busy=value;for(const id of ['previous','next','save','jump'])$(id).disabled=value;$('vote').querySelectorAll('input,textarea').forEach(e=>e.disabled=value);if(!value){$('previous').disabled=position===0;$('next').disabled=position===overview.pairs.length-1;}}
async function loadPair(nextPosition){
 if(busy)return;
 if(dirty&&!confirm('当前修改尚未提交。放弃修改并切换？')){$('jump').value=String(position);return;}
 setBusy(true);$('error').hidden=true;
 try{const entry=overview.pairs[nextPosition],pair=await api('/api/pair?index='+entry.index);position=nextPosition;
 $('requirement').textContent=pair.requirement;math($('requirement'));
 renderSide($('side-a'),pair.candidates[0],0,entry.index);renderSide($('side-b'),pair.candidates[1],1,entry.index);
 $('vote').reset();if(pair.vote)$('vote').querySelector('[value="'+pair.vote.choice+'"]').checked=true;
 $('reason').value=pair.vote?.reason||'';dirty=false;$('saved').textContent=pair.vote?'已保存，可修改后重新提交':'尚未提交';updateProgress();
 }catch(e){showError(e);$('jump').value=String(position);}finally{setBusy(false);}
}
function updateProgress(){const n=overview.pairs.filter(p=>p.vote).length;$('progress').textContent='已评 '+n+' / '+overview.pairs.length;$('jump').replaceChildren(...overview.pairs.map((p,i)=>{const o=make('option','第 '+(i+1)+' 组'+(p.vote?' · 已评':''));o.value=i;return o;}));$('jump').value=position;}
async function enter(value){token=value;overview=await api('/api/overview');localStorage.setItem(storageKey,token);$('title').textContent=overview.title;$('session-code').textContent=token;$('account').hidden=false;$('login').hidden=true;$('review').hidden=false;position=0;const first=overview.pairs.findIndex(p=>!p.vote);await loadPair(first<0?0:first);}
$('start').onclick=async()=>{try{$('start').disabled=true;const s=await api('/api/session',{});await enter(s.session);}catch(e){showError(e);}finally{$('start').disabled=false;}};
$('resume').onclick=async()=>{try{await enter($('restore').value.trim());}catch(e){showError(e);}};
$('logout').onclick=()=>{if(dirty&&!confirm('当前修改尚未提交，仍要退出？'))return;localStorage.removeItem(storageKey);dirty=false;location.reload();};
$('previous').onclick=()=>loadPair(position-1);$('next').onclick=()=>loadPair(position+1);$('jump').onchange=()=>loadPair(Number($('jump').value));
$('vote').oninput=()=>{dirty=true;$('saved').textContent='有未提交修改';};
$('vote').onsubmit=async e=>{e.preventDefault();if(busy)return;const choice=new FormData($('vote')).get('choice');if(!choice)return;setBusy(true);
 try{const entry=overview.pairs[position];entry.vote=await api('/api/vote',{pair:entry.index,choice,reason:$('reason').value});dirty=false;updateProgress();$('saved').textContent='已保存';setBusy(false);
 const next=overview.pairs.findIndex((p,i)=>i>position&&!p.vote);const earlier=overview.pairs.findIndex(p=>!p.vote);if(next>=0||earlier>=0){await loadPair(next>=0?next:earlier);window.scrollTo({top:0});}else $('saved').textContent='全部已提交。你可以回看并修改选择。';
 }catch(e){showError(e);}finally{setBusy(false);}};
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
try{const saved=localStorage.getItem(storageKey);if(saved)enter(saved).catch(showError);}catch(e){showError(e);}
</script></body></html>'''
