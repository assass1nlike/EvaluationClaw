// Usage: NODE_PATH=/path/to/node_modules node paper/figures/human_judge/render.cjs
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
 const examples=JSON.parse(fs.readFileSync(path.join(__dirname,'examples.json'),'utf8'));
 const html=fs.readFileSync(path.resolve(__dirname,'../../../benchmark-output/paper-human-judge/interface.html'),'utf8');
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:960,height:1800},deviceScaleFactor:2});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://review.invalid/',route=>route.fulfill({contentType:'text/html',body:html}));
 for(const example of examples){
  await page.goto('http://review.invalid/');
  await page.evaluate(example=>{
   const kinds={choice:'Multiple choice',generation:'Free response',multi_turn:'Multi-turn',agent:'Agent'};
   $('login').hidden=true;$('error').hidden=true;$('review').hidden=false;
   $('title').textContent='Task quality comparison';
   $('reason').placeholder='Reason (optional)';
   $('requirement').textContent=example.requirement;
   renderSide($('side-a'),example.candidates[0],0,0);
   renderSide($('side-b'),example.candidates[1],1,0);
   for(const [i,id] of ['side-a','side-b'].entries()){
    const node=$(id);
    node.querySelector('.side-head').append(make('span',kinds[example.candidates[i].kind],'task-kind'));
    for(const detail of node.querySelectorAll(':scope>details')){
     const title=detail.querySelector('summary').textContent;
     if(title.startsWith('Recorded answer')||title.startsWith('Recorded reference')||title.startsWith('Environment and grading'))detail.open=true;
    }
   }
   const note=make('p','Print illustration · Longer task and evidence records are excerpted.','illustration-note');
   document.querySelector('header>div').append(note);
   document.querySelectorAll('a').forEach(a=>a.removeAttribute('href'));
  },example);
  await page.evaluate(()=>document.fonts.ready);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const content=await page.locator('main').innerText();
  assert(!/[\u3400-\u9fff]/u.test(content),'Untranslated UI text');
  assert(!/evalclaw|autobencher/i.test(content),'Source label visible');
  assert.equal(await page.locator('input[type=radio]:checked').count(),0);
  assert.equal(await page.locator('input[type=radio]').count(),2);
  const height=await page.evaluate(()=>Math.ceil(document.querySelector('main').getBoundingClientRect().bottom));
  assert(height<1700,'Figure too tall for one appendix page: '+example.name+' '+height);
  await page.screenshot({path:path.join(__dirname,example.name+'.png'),clip:{x:0,y:0,width:960,height}});
  await page.pdf({path:path.join(__dirname,example.name+'.pdf'),width:'960px',height:height+'px',
                 printBackground:true,margin:{top:0,bottom:0,left:0,right:0}});
  console.log(example.name+': 960 x '+height+' px; vector PDF and 2x PNG');
 }
 assert.deepEqual(errors,[]);
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
