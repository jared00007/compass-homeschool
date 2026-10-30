"""The Slope & Intercept Explorer -- a hands-on grapher for linear relationships.

A struggling 8th-grader doesn't need another video; he needs to *move* the line
and watch what moves with it. This is a self-contained HTML/Canvas manipulative:
two sliders (how steep, where it starts) drive a line on a grid, and the table,
the equation, and the real-world meaning all update together in real time -- so
"the slope, the unit rate, the number in y = mx + b, and the steepness of the
line are the SAME number" stops being four facts and becomes one thing he can
see. Guided missions walk the exact rungs the Math graph lists
(proportional -> constant of proportionality -> graphing -> slope ->
slope-intercept), ending with a "match the mystery line" game that makes him
read a graph backwards.

Pure client-side: it runs in the components iframe and makes zero model calls,
so he can play with it for an hour at no cost. Colors are the app's own fixed
light ("Sunday Funnies") palette, hard-coded here since the iframe doesn't
inherit the page's theme CSS (same reason the spelling card carries its own).
"""

from __future__ import annotations

# The whole widget is one static document -- no values are interpolated in, so
# it carries no f-string / .format braces to escape. Edit the HTML/JS directly.
_EXPLORER_HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{
    --paper:#FFFBF0; --ink:#241C12; --dim:#8A7A5E; --border:#2E5EAA;
    --line:#2F63E0; --accent:#F2B705; --good:#2F9B68; --bad:#C43B32;
    --grid:#E7DFC9; --grid-strong:#D3C7A3;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--paper);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  .wrap{display:flex;flex-wrap:wrap;gap:16px;padding:14px;align-items:flex-start;}
  .col{flex:1 1 320px;min-width:280px;}
  .card{background:#fff;border:2px solid var(--border);border-radius:12px;
    padding:11px 13px;box-shadow:0 2px 0 rgba(46,94,170,.15);}
  canvas{width:100%;height:auto;display:block;border-radius:8px;}
  h2{font-size:16px;margin:0 0 3px;}
  .sub{color:var(--dim);font-size:12.5px;margin:0 0 7px;}
  .badge{display:inline-block;font-weight:800;font-size:13px;padding:4px 10px;
    border-radius:999px;margin-top:10px;}
  .badge.prop{background:#E1F0E6;color:var(--good);}
  .badge.notprop{background:#FCEFD1;color:var(--warn,#B9791A);}
  .eq{font-size:30px;font-weight:800;letter-spacing:.5px;text-align:center;
    margin:6px 0 2px;font-variant-numeric:tabular-nums;}
  .eq .m{color:var(--line);} .eq .b{color:var(--accent);
    text-shadow:0 0 1px #b8860b,0 0 1px #b8860b;}
  .ctrl{margin:14px 0;}
  .ctrl label{display:flex;justify-content:space-between;font-weight:700;font-size:14px;
    margin-bottom:4px;}
  .ctrl .val{font-variant-numeric:tabular-nums;}
  .row{display:flex;align-items:center;gap:8px;}
  input[type=range]{flex:1;height:26px;accent-color:var(--line);}
  .ctrl.b input[type=range]{accent-color:var(--accent);}
  .stepper{border:2px solid var(--border);background:#fff;color:var(--ink);
    font-weight:800;font-size:18px;width:34px;height:34px;border-radius:8px;
    cursor:pointer;line-height:1;}
  .stepper:active{transform:translateY(1px);}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;
    margin-top:6px;}
  th,td{border:1px solid var(--grid-strong);padding:5px 6px;text-align:center;font-size:14px;}
  th{background:#F6EFDA;}
  .tiny{color:var(--dim);font-size:12px;margin-top:6px;}
  .missions{list-style:none;padding:0;margin:8px 0 0;}
  .missions li{display:flex;align-items:center;gap:9px;padding:5px 4px;
    border-bottom:1px dashed var(--grid-strong);font-size:13.5px;}
  .missions li:last-child{border-bottom:none;}
  .chk{flex:0 0 22px;height:22px;border-radius:50%;border:2px solid var(--grid-strong);
    display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;color:#fff;}
  .missions li.done .chk{background:var(--good);border-color:var(--good);}
  .missions li.done{color:var(--good);font-weight:700;}
  .match{margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
  .match .status{font-weight:800;}
  .steps{list-style:none;padding:0;margin:8px 0;}
  .steps li{display:flex;gap:9px;align-items:flex-start;padding:6px 4px;
    border-bottom:1px dashed var(--grid-strong);}
  .steps li:last-child{border-bottom:none;}
  .steps .dot{flex:0 0 22px;height:22px;border-radius:50%;border:2px solid var(--grid-strong);
    margin-top:1px;display:flex;align-items:center;justify-content:center;
    font-size:13px;font-weight:900;color:#fff;}
  .steps li.ok .dot{background:var(--good);border-color:var(--good);}
  .steps li.ok .dot::after{content:"\2713";}
  .fb{font-size:13px;color:var(--dim);}
  .steps li.ok .fb{color:var(--good);font-weight:700;}
  .matchbig{font-weight:800;font-size:15px;margin:10px 0 6px;}
  .btn.ghost{background:#fff;}
  .hintbox{margin-top:9px;font-size:14px;line-height:1.4;background:#FFF6D9;
    border:1px solid var(--accent);border-radius:9px;padding:9px 11px;display:none;}
  .modebar{display:flex;gap:8px;margin-bottom:12px;}
  .modebtn{flex:1;border:2px solid var(--border);background:#fff;color:var(--ink);
    font-weight:800;font-size:14px;padding:9px;border-radius:10px;cursor:pointer;}
  .modebtn.active{background:var(--line);color:#fff;}
  .pctrls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:13px;margin-bottom:6px;}
  .pctrls select{font-size:13px;padding:4px 6px;border-radius:7px;border:2px solid var(--border);
    background:#fff;color:var(--ink);font-weight:700;}
  .pmastery{margin:4px 0 10px;}
  .pbadge{display:inline-block;font-size:11.5px;font-weight:800;background:#F6EFDA;
    border:1px solid var(--grid-strong);border-radius:999px;padding:3px 8px;margin:0 4px 4px 0;
    font-variant-numeric:tabular-nums;}
  .pprompt{font-size:15px;line-height:1.45;margin:4px 0 8px;}
  .pprompt .peq{font-weight:800;color:var(--line);font-size:17px;}
  .pnums{display:flex;gap:12px;flex-wrap:wrap;margin:6px 0;}
  .pnums label{font-weight:700;font-size:13px;display:flex;flex-direction:column;gap:3px;}
  .pnum{width:110px;font-size:17px;padding:7px 8px;border-radius:8px;border:2px solid var(--border);
    font-variant-numeric:tabular-nums;}
  .pmc{margin-top:6px;}
  .pmcopt{display:block;font-size:13.5px;padding:5px 2px;cursor:pointer;}
  .pmcopt input{margin-right:7px;}
  .btn{border:2px solid var(--border);background:var(--accent);color:var(--ink);
    font-weight:800;font-size:14px;padding:8px 12px;border-radius:9px;cursor:pointer;}
  .btn:active{transform:translateY(1px);}
  .legend{font-size:12px;color:var(--dim);margin-top:8px;}
  .legend b.l{color:var(--line);} .legend b.t{color:var(--accent);}
  /* slope = blue, intercept = gold, used everywhere so the equation, the graph,
     and the words all share the same two colors. */
  .mk{color:var(--line);} .bk{color:#b8860b;}
  .startcell{background:#FCEFD1 !important;font-weight:800;}
  .notice-card{border-color:var(--accent);box-shadow:0 2px 0 rgba(242,183,5,.25);}
  .notice-card h2{color:#9a6b00;}
  .notice{font-size:14.5px;line-height:1.5;}
  .notice .nrow{padding:4px 0;border-bottom:1px dashed var(--grid-strong);}
  .notice .nrow:last-child{border-bottom:none;}
  .notice .nrow.good{color:var(--good);font-weight:700;}
  .notice .nrow.warn{color:#9a6b00;font-weight:700;}
  .remember{margin-top:12px;background:#EDF2FB;border:2px dashed var(--border);
    border-radius:12px;padding:11px 13px;font-size:13px;line-height:1.55;}
  .remember .rhead{font-weight:800;font-size:14px;margin-bottom:4px;}
  .remember div{margin:2px 0;}
</style>
</head>
<body>
<div class="wrap">
  <!-- Left: the graph itself -->
  <div class="col">
    <div class="card">
      <h2>📈 The line</h2>
      <p class="sub">Move the sliders and watch the line, the table, and the equation change together.</p>
      <canvas id="grid" width="460" height="460"></canvas>
      <div id="badge" class="badge prop">✓ Proportional — it goes through the corner (0, 0)</div>
      <div class="legend">
        <b class="l">━━ your line</b> &nbsp;·&nbsp; <b class="t">●</b> where it starts (the y-intercept)
        &nbsp;·&nbsp; <span style="color:#888">- - - mystery line</span>
      </div>
    </div>

    <div class="card notice-card" style="margin-top:10px;">
      <h2>🧠 What to notice</h2>
      <div id="notice" class="notice"></div>
    </div>

    <div class="remember">
      <div class="rhead">📌 Remember this</div>
      <div><b class="mk">m</b> = <b class="mk">slope</b> = rise ÷ run = <b>the rate</b> (how steep). Bigger m = steeper.</div>
      <div><b class="bk">b</b> = <b class="bk">y-intercept</b> = <b>where it starts</b> — its value when x = 0.</div>
      <div><b class="bk">b = 0</b> → it goes through the corner <b>(0, 0)</b> → <b>proportional</b>.</div>
      <div>Equation: <b>y = <span class="mk">m</span>x + <span class="bk">b</span></b>.</div>
    </div>
  </div>

  <!-- Right: controls, equation, table, missions / practice -->
  <div class="col">
    <div class="modebar">
      <button id="modeExplore" class="modebtn active">🎛️ Explore</button>
      <button id="modePractice" class="modebtn">🎓 Practice</button>
    </div>
    <div class="card">
      <div id="eq" class="eq">y = <span class="m">1</span>x</div>

      <div class="ctrl slope">
        <label>How steep is it? <span class="val">slope = <b id="mval">1</b></span></label>
        <div class="row">
          <button class="stepper" id="mdown" aria-label="less steep">−</button>
          <input type="range" id="m" min="-5" max="5" step="0.5" value="1">
          <button class="stepper" id="mup" aria-label="more steep">+</button>
        </div>
        <div class="tiny">This is the <b>unit rate</b> — how much y goes up for every 1 step right.</div>
      </div>

      <div class="ctrl b">
        <label>Where does it start? <span class="val">y-intercept = <b id="bval">0</b></span></label>
        <div class="row">
          <button class="stepper" id="bdown" aria-label="start lower">−</button>
          <input type="range" id="b" min="-10" max="10" step="1" value="0">
          <button class="stepper" id="bup" aria-label="start higher">+</button>
        </div>
        <div class="tiny">Where the line crosses the y-axis — its value when x = 0.</div>
      </div>

      <table>
        <thead><tr><th>x</th><th>0</th><th>1</th><th>2</th><th>3</th><th>4</th></tr></thead>
        <tbody><tr><th>y</th><td id="y0" class="startcell">0</td><td id="y1">1</td><td id="y2">2</td><td id="y3">3</td><td id="y4">4</td></tr></tbody>
      </table>
      <div class="tiny">The gold cell (x = 0) is <b class="bk">b</b>, where it starts. Each step right, y jumps by <b class="mk">m</b> (the slope).</div>
    </div>

    <div id="exploreExtras">
    <div class="card" style="margin-top:10px;">
      <h2>🎯 Missions</h2>
      <p class="sub">Dial the line to make each one true.</p>
      <ul id="missions" class="missions"></ul>

    </div>

    <div class="card" style="margin-top:10px;">
      <h2>🔍 Mystery Line Challenge</h2>
      <p class="sub">A dashed line is hiding on the graph. Match it in just two steps —
        and if you're stuck, <b>💡 Hint</b> walks you through reading it.</p>
      <ol class="steps">
        <li id="step1"><span class="dot"></span><div>
          <b>① Where does it start?</b><br>
          <span id="fb_start" class="fb">Find where the dashed line crosses the up–down axis, and set “where it starts” there.</span>
        </div></li>
        <li id="step2"><span class="dot"></span><div>
          <b>② How steep is it?</b><br>
          <span id="fb_steep" class="fb">From that start, go right 1 — count how far up (or down) the dashed line goes.</span>
        </div></li>
      </ol>
      <div id="matchbig" class="matchbig">Dial your solid line onto the dashed one.</div>
      <div class="match">
        <button id="hintbtn" class="btn ghost">💡 Hint</button>
        <button id="newline" class="btn">🎲 New line</button>
        <span id="matchcount" class="tiny"></span>
      </div>
      <div id="hintbox" class="hintbox"></div>
    </div>
    </div><!-- /exploreExtras -->

    <div id="practiceCard" class="card" style="margin-top:10px;display:none;">
      <h2>🎓 Practice</h2>
      <div class="pctrls">
        <label>Level
          <select id="plevel">
            <option value="1">1 · Proportional (through 0,0)</option>
            <option value="2">2 · Add a starting point</option>
            <option value="3">3 · Negatives too</option>
            <option value="4">4 · Fractions &amp; word problems</option>
          </select>
        </label>
        <span id="pstreak" class="tiny"></span>
        <span id="psolved" class="tiny"></span>
      </div>
      <div id="pmastery" class="pmastery"></div>
      <div id="pprompt" class="pprompt"></div>
      <div id="panswer" class="panswer"></div>
      <div class="match">
        <button id="pcheck" class="btn">✓ Check</button>
        <button id="pshow" class="btn ghost">👀 Show me</button>
        <button id="pnext" class="btn ghost">→ New problem</button>
      </div>
      <div id="pfeedback" class="hintbox"></div>
    </div>
  </div>
</div>

<script>
(function(){
  var XMIN=-10, XMAX=10, YMIN=-10, YMAX=10;
  var cv = document.getElementById('grid');
  var ctx = cv.getContext('2d');
  var mEl=document.getElementById('m'), bEl=document.getElementById('b');
  var target = null, matches = 0, hintIdx = 0;
  var mode = 'explore';

  function sizeCanvas(){
    var cssW = cv.clientWidth || 460;
    var dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(cssW*dpr);
    cv.height = Math.round(cssW*dpr); // square
    ctx.setTransform(dpr,0,0,dpr,0,0);
    draw();
    fitFrame();
  }

  // Grow this component's own iframe to fit its content so it never shows an
  // inner scrollbar -- the whole tool stays in view and the page scrolls as one,
  // not a box-within-a-box. The srcdoc frame is same-origin, so frameElement is
  // reachable; wrapped in try/catch in case a browser blocks it. Reported: "that
  // whole container for the graphing needs to be in view. no scroller."
  function fitFrame(){
    try{
      var h = Math.ceil(document.body.getBoundingClientRect().height) + 2;
      var fe = window.frameElement;
      if(fe){
        fe.style.height = h+'px'; fe.setAttribute('height', h);
        var w = fe.parentElement, n = 0;
        while(w && n < 4){ if(w.style){ w.style.height='auto'; w.style.maxHeight='none'; } w = w.parentElement; n++; }
      }
    }catch(e){}
  }

  function W(){return cv.clientWidth || 460;}
  function H(){return cv.clientWidth || 460;}
  var PAD = 24;
  function px(x){ return PAD + (x-XMIN)/(XMAX-XMIN)*(W()-2*PAD); }
  function py(y){ return PAD + (YMAX-y)/(YMAX-YMIN)*(H()-2*PAD); }

  function nice(n){ // trim -0 and trailing .0
    if(Object.is(n,-0)) n=0;
    return (Math.round(n*100)/100).toString();
  }

  function drawGrid(){
    ctx.clearRect(0,0,W(),H());
    ctx.lineWidth=1;
    for(var x=XMIN;x<=XMAX;x++){
      ctx.strokeStyle = (x%5===0)? '#D3C7A3':'#E7DFC9';
      ctx.beginPath(); ctx.moveTo(px(x),py(YMIN)); ctx.lineTo(px(x),py(YMAX)); ctx.stroke();
    }
    for(var y=YMIN;y<=YMAX;y++){
      ctx.strokeStyle = (y%5===0)? '#D3C7A3':'#E7DFC9';
      ctx.beginPath(); ctx.moveTo(px(XMIN),py(y)); ctx.lineTo(px(XMAX),py(y)); ctx.stroke();
    }
    // axes
    ctx.strokeStyle='#241C12'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(px(XMIN),py(0)); ctx.lineTo(px(XMAX),py(0)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(px(0),py(YMIN)); ctx.lineTo(px(0),py(YMAX)); ctx.stroke();
    // axis numbers (every 5, skip 0)
    ctx.fillStyle='#8A7A5E'; ctx.font='11px sans-serif';
    ctx.textAlign='center'; ctx.textBaseline='top';
    for(var xa=XMIN;xa<=XMAX;xa+=5){ if(xa!==0){ ctx.fillText(xa, px(xa), py(0)+3); } }
    ctx.textAlign='left'; ctx.textBaseline='middle';
    for(var ya=YMIN;ya<=YMAX;ya+=5){ if(ya!==0){ ctx.fillText(ya, px(0)+4, py(ya)); } }
    // origin dot
    ctx.fillStyle='#241C12';
    ctx.beginPath(); ctx.arc(px(0),py(0),3,0,7); ctx.fill();
  }

  function drawLineFor(m,b,color,dashed){
    ctx.save();
    ctx.strokeStyle=color; ctx.lineWidth=dashed?2.5:4;
    if(dashed) ctx.setLineDash([9,7]); else ctx.setLineDash([]);
    // clip to the plot rectangle so steep lines don't scrawl over labels
    ctx.beginPath();
    ctx.rect(px(XMIN),py(YMAX),px(XMAX)-px(XMIN),py(YMIN)-py(YMAX));
    ctx.clip();
    ctx.beginPath();
    ctx.moveTo(px(XMIN), py(m*XMIN+b));
    ctx.lineTo(px(XMAX), py(m*XMAX+b));
    ctx.stroke();
    ctx.restore();
  }

  function drawSlopeTriangle(m,b){
    if(m===0) return;
    // from (0,b) run +1 to (1,b), rise +m to (1, b+m)
    ctx.save();
    ctx.beginPath();
    ctx.rect(px(XMIN),py(YMAX),px(XMAX)-px(XMIN),py(YMIN)-py(YMAX)); ctx.clip();
    ctx.strokeStyle='#C43B32'; ctx.fillStyle='#C43B32'; ctx.lineWidth=2;
    ctx.setLineDash([4,3]);
    ctx.beginPath(); ctx.moveTo(px(0),py(b)); ctx.lineTo(px(1),py(b)); ctx.stroke();      // run
    ctx.beginPath(); ctx.moveTo(px(1),py(b)); ctx.lineTo(px(1),py(b+m)); ctx.stroke();     // rise
    ctx.setLineDash([]);
    ctx.font='bold 12px sans-serif';
    // Start just past the intercept dot (radius ~7px) so it never sits under it.
    ctx.textAlign='left'; ctx.textBaseline='top';
    ctx.fillText('right 1', px(0)+11, py(b)+3);
    ctx.textBaseline='middle';
    ctx.fillText((m>0?'up ':'down ')+nice(Math.abs(m))+'  = slope '+nice(m), px(1)+4, py(b+m/2));
    ctx.restore();
  }

  function drawIntercept(b){
    ctx.save();
    ctx.fillStyle='#F2B705'; ctx.strokeStyle='#241C12'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.arc(px(0),py(b),7,0,7); ctx.fill(); ctx.stroke();
    ctx.fillStyle='#b8860b'; ctx.font='bold 12px sans-serif';
    // Label sits to the LEFT of the y-axis so it never collides with the slope
    // triangle's "right 1 / up N" labels, which run off to the right. Gold, to
    // match the intercept everywhere else.
    ctx.textAlign='right'; ctx.textBaseline='bottom';
    ctx.fillText('b = (0, '+nice(b)+')', px(0)-10, py(b)-6);
    ctx.restore();
  }

  function fmtEq(m,b){
    var mp;
    if(m===1) mp='x'; else if(m===-1) mp='−x'; else mp=nice(m)+'x';
    var bp;
    if(b>0) bp=' + <span class="b">'+nice(b)+'</span>';
    else if(b<0) bp=' − <span class="b">'+nice(Math.abs(b))+'</span>';
    else bp='';
    if(m===0) return 'y = <span class="b">'+nice(b)+'</span>';
    return 'y = <span class="m">'+mp+'</span>'+bp;
  }

  var MISSIONS = [
    {text:'Make it go straight through the corner (0, 0) — that’s what "proportional" means.',
     test:function(m,b){return b===0;}},
    {text:'Make it climb 3 for every 1 step right (slope = 3).',
     test:function(m,b){return m===3;}},
    {text:'Now make it START at 5 before it climbs (y-intercept = 5).',
     test:function(m,b){return b===5;}},
    {text:'Make a flat line that never climbs (slope = 0).',
     test:function(m,b){return m===0;}},
    {text:'Make it head downhill (a negative slope).',
     test:function(m,b){return m<0;}}
  ];

  function buildMissions(){
    var ul=document.getElementById('missions');
    MISSIONS.forEach(function(ms,i){
      var li=document.createElement('li'); li.id='mi'+i;
      li.innerHTML='<span class="chk">✓</span><span>'+ms.text+'</span>';
      ul.appendChild(li);
    });
  }

  function fmtPlain(m,b){ // plain-text equation for the reveal hint
    var mp = (m===1)?'x':(m===-1)?'-x':(nice(m)+'x');
    var bp = (b>0)?(' + '+nice(b)):(b<0)?(' - '+nice(Math.abs(b))):'';
    if(m===0) return nice(b);
    return mp+bp;
  }

  function fmtEqColored(m,b){ // equation with slope blue, intercept gold
    var mp = (m===1)?'x':(m===-1)?'-x':(nice(m)+'x');
    var bp = (b>0)?(' + <span class="bk">'+nice(b)+'</span>')
      :(b<0)?(' − <span class="bk">'+nice(Math.abs(b))+'</span>'):'';
    if(m===0) return 'y = <span class="bk">'+nice(b)+'</span>';
    return 'y = <span class="mk">'+mp+'</span>'+bp;
  }

  // The always-on "What to notice" panel: in plain words, the two things that
  // matter about the line on the graph right now -- where it STARTS (b) and how
  // STEEP it is (m) -- plus whether it's proportional. In Practice, before he's
  // answered a read-the-graph/word problem it shows the METHOD instead (so it
  // doesn't hand him the answer).
  function updateNotice(cm,cb,narrate){
    var el=document.getElementById('notice'); if(!el) return;
    if(!narrate){
      el.innerHTML=
        '<div class="nrow">🔎 <b>How to read any line — 3 steps:</b></div>'+
        '<div class="nrow"><b class="bk">①</b> Where does it cross the up–down axis? That number is '+
          '<b class="bk">b</b> — where it starts.</div>'+
        '<div class="nrow"><b class="mk">②</b> From there go <b>right 1</b> and count <b class="mk">up or down</b>. '+
          'That number is <b class="mk">m</b> — the slope.</div>'+
        '<div class="nrow">③ Put them together: <b>y = <span class="mk">m</span>x + <span class="bk">b</span></b>.</div>';
      return;
    }
    var steep = (cm===0)
      ? 'the line stays <b>flat</b> (slope 0 — y never changes)'
      : 'go <b>right 1</b>, then <b class="mk">'+(cm>0?'up':'down')+' '+nice(Math.abs(cm))+'</b>';
    var prop = (cb===0)
      ? '<div class="nrow good">✅ b = 0 → it runs through the corner <b>(0, 0)</b> → <b>PROPORTIONAL</b>.</div>'
      : '<div class="nrow warn">⚠️ b = '+nice(cb)+' (not 0) → it does NOT pass through the corner → not proportional.</div>';
    el.innerHTML=
      '<div class="nrow">📍 <b class="bk">b = '+nice(cb)+'</b> — the line crosses the y-axis at '+
        '<b class="bk">(0, '+nice(cb)+')</b>. That’s where it <b>STARTS</b>.</div>'+
      '<div class="nrow">📈 <b class="mk">m = '+nice(cm)+'</b> — from the start, '+steep+
        '. That’s the <b>SLOPE</b> (the rate).</div>'+
      '<div class="nrow">🧮 Together: <b>'+fmtEqColored(cm,cb)+'</b></div>'+
      prop;
  }

  function newTarget(){
    var ms=[-3,-2,-1,-0.5,0.5,1,2,3];
    var m=ms[Math.floor(Math.random()*ms.length)];
    var b=Math.floor(Math.random()*13)-6; // -6..6
    target={m:m,b:b};
    hintIdx=0;
    var hb=document.getElementById('hintbox'); hb.style.display='none'; hb.innerHTML='';
    draw();
  }

  function drawGhostStart(b){ // mark the mystery line's starting point on the y-axis
    ctx.save();
    ctx.fillStyle='#9AA0A6'; ctx.strokeStyle='#fff'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.arc(px(0),py(b),6,0,7); ctx.fill(); ctx.stroke();
    ctx.restore();
  }

  function draw(){
    var m=parseFloat(mEl.value), b=parseFloat(bEl.value);

    // Live slider readouts update in both modes.
    document.getElementById('mval').textContent=nice(m);
    document.getElementById('bval').textContent=nice(b);
    document.getElementById('eq').innerHTML=fmtEq(m,b);
    for(var i=0;i<=4;i++){ document.getElementById('y'+i).textContent=nice(m*i+b); }
    var badge=document.getElementById('badge');
    if(b===0){ badge.className='badge prop';
      badge.innerHTML='✓ Proportional — it goes through the corner (0, 0)'; }
    else{ badge.className='badge notprop';
      badge.innerHTML='Not proportional — it starts at (0, '+nice(b)+'), not the corner'; }

    // Narrate the line that's actually on screen (method-only mid-problem).
    if(mode==='explore'){ updateNotice(m,b,true); }
    else if(P.cur){
      if(P.cur.type==='B'){ updateNotice(m,b,true); }
      else if(P.answered){ updateNotice(P.cur.m,P.cur.b,true); }
      else { updateNotice(null,null,false); }
    }

    drawGrid();
    if(mode==='practice'){ drawPracticeCanvas(m,b); return; }

    // --- Explore mode: his line + the mystery-line challenge ---
    if(target){ drawLineFor(target.m,target.b,'#9AA0A6',true); drawGhostStart(target.b); }
    drawLineFor(m,b,'#2F63E0',false);
    drawSlopeTriangle(m,b);
    drawIntercept(b);

    MISSIONS.forEach(function(ms,i){
      document.getElementById('mi'+i).classList.toggle('done', ms.test(m,b));
    });

    if(target){
      var startOk = Math.abs(b-target.b)<1e-9;
      var steepOk = Math.abs(m-target.m)<1e-9;
      var fs=document.getElementById('fb_start'), ft=document.getElementById('fb_steep');
      // Step ① — where it starts, with a direction to move.
      if(startOk){ fs.textContent='✓ matches'; }
      else if(b<target.b){ fs.textContent='your start is too LOW — slide “where it starts” UP'; }
      else { fs.textContent='your start is too HIGH — slide “where it starts” DOWN'; }
      // Step ② — how steep, with a direction.
      if(steepOk){ ft.textContent='✓ matches'; }
      else if(m===0 && target.m!==0){ ft.textContent="it's not flat — tilt it"; }
      else if((m>0)!==(target.m>0) && m!==0 && target.m!==0){
        ft.textContent='it leans the OTHER way — flip it '+(target.m>0?'uphill':'downhill'); }
      else if(Math.abs(m)<Math.abs(target.m)){ ft.textContent='close — make it STEEPER'; }
      else { ft.textContent='close — make it LESS steep'; }
      document.getElementById('step1').classList.toggle('ok', startOk);
      document.getElementById('step2').classList.toggle('ok', steepOk);

      var mb=document.getElementById('matchbig');
      if(startOk && steepOk){
        mb.textContent='🎉 Matched! You read the line.'; mb.style.color='#2F9B68';
        if(!target.counted){ target.counted=true; matches++;
          document.getElementById('matchcount').textContent='solved: '+matches; } }
      else{ mb.textContent='Dial your solid line onto the dashed one.'; mb.style.color=''; }
    }
  }

  function showHint(){
    var hints=[
      '<b>Step ①.</b> Find where the <b>dashed</b> line crosses the up–down axis '
        +'(look for the gray dot). Move <b>“where it starts”</b> to that number.',
      '<b>Step ②.</b> Put your finger on that gray start dot. Go <b>right 1</b> square — '
        +'count how many the dashed line goes <b>up</b> (or down = a minus). '
        +'Set <b>“how steep”</b> to that.',
      '<b>The answer:</b> the mystery line is <b>y = '+fmtPlain(target.m,target.b)
        +'</b>. Dial your sliders to exactly that and watch it land.'
    ];
    var hb=document.getElementById('hintbox');
    hb.style.display='block';
    hb.innerHTML='💡 '+hints[Math.min(hintIdx,2)];
    if(hintIdx<2) hintIdx++;
  }

  function clamp(el){ var v=parseFloat(el.value),
    lo=parseFloat(el.min), hi=parseFloat(el.max);
    el.value=Math.max(lo,Math.min(hi,v)); }
  function step(el,dir){ el.value=parseFloat(el.value)+dir*parseFloat(el.step);
    clamp(el); draw(); }

  // =====================================================================
  //  PRACTICE MODE — real problems, checking, feedback, levels, mastery.
  //  Problems are generated in the browser (infinite reps, zero cost) across
  //  three types: A read-a-graph -> equation, B equation -> graph (dial the
  //  sliders), D word problem -> equation + what the slope means. Levels
  //  scaffold: 1 proportional, 2 add an intercept, 3 negatives, 4 fractions
  //  & word problems. "Show me" loads the answer onto the graph so he connects
  //  the problem to the picture.
  // =====================================================================
  var P = { level:1, streak:0, solved:0, cur:null, answered:false, meaning:null,
            byType:{A:{ok:0,n:0}, B:{ok:0,n:0}, D:{ok:0,n:0}} };
  function rnd(lo,hi){ return Math.floor(Math.random()*(hi-lo+1))+lo; }
  function pick(a){ return a[Math.floor(Math.random()*a.length)]; }
  function shuffle(a){ a=a.slice(); for(var i=a.length-1;i>0;i--){ var j=Math.floor(Math.random()*(i+1)); var t=a[i];a[i]=a[j];a[j]=t; } return a; }
  function near(a,bb){ a=parseFloat(a); return !isNaN(a) && Math.abs(a-bb)<1e-9; }

  var WORD_CTX=[
    {unit:'hour',  verb:'of work',  xlabel:'hours worked', ylabel:'total cost ($)',
     build:function(r,s){return 'A plumber charges $'+s+' just to show up, plus $'+r+' for each hour of work.';}},
    {unit:'mile',  verb:'driven',   xlabel:'miles driven', ylabel:'total fare ($)',
     build:function(r,s){return 'A taxi costs $'+s+' to start, plus $'+r+' for every mile driven.';}},
    {unit:'month', verb:'',         xlabel:'months', ylabel:'total paid ($)',
     build:function(r,s){return 'A gym charges a $'+s+' sign-up fee, plus $'+r+' every month.';}},
    {unit:'day',   verb:'',         xlabel:'days', ylabel:'money saved ($)',
     build:function(r,s){return 'You start with $'+s+' saved and add $'+r+' every day.';}}
  ];

  function slopeFor(level){
    if(level<=2) return rnd(1,5);
    if(level===3){ var v=rnd(1,5); return Math.random()<0.5?-v:v; }
    return pick([0.5,1,1.5,2,2.5,3,-0.5,-1,-1.5,-2,-2.5,-3]);
  }
  function interceptFor(level){
    if(level===1) return 0;
    if(level===2) return rnd(1,6);
    return rnd(-6,6);
  }

  function genProblem(level){
    var types = level>=2 ? ['A','B','D'] : ['A','B'];  // word problems have a start, so L2+
    var type=pick(types);
    if(type==='D'){
      return {type:'D', m:rnd(2,9), b:rnd(5,40), ctx:pick(WORD_CTX)};
    }
    var m=slopeFor(level); if(m===0) m=1;
    return {type:type, m:m, b:interceptFor(level)};
  }

  function numInputs(){
    return '<div class="pnums">'
      +'<label>slope (m)<input type="number" step="0.5" id="pm" class="pnum" placeholder="?"></label>'
      +'<label>y-intercept (b)<input type="number" step="1" id="pb" class="pnum" placeholder="?"></label></div>';
  }

  function renderProblem(){
    var p=P.cur, prompt=document.getElementById('pprompt'), ans=document.getElementById('panswer');
    var fb=document.getElementById('pfeedback'); fb.style.display='none'; fb.innerHTML='';
    if(p.type==='A'){
      prompt.innerHTML='📈 <b>Read the purple line</b> on the graph. What is its equation?';
      ans.innerHTML=numInputs();
    } else if(p.type==='B'){
      prompt.innerHTML='🎯 <b>Graph this line:</b> <span class="peq">y = '+fmtPlain(p.m,p.b)
        +'</span><br><span class="tiny">Use the two sliders above to match it, then press Check.</span>';
      ans.innerHTML='';
    } else {
      prompt.innerHTML='🧮 '+p.ctx.build(p.m,p.b)
        +'<br><span class="tiny">Let x = '+p.ctx.xlabel+', y = '+p.ctx.ylabel+'.</span>';
      var opts=shuffle([
        {t:'It costs $'+p.m+' more for each extra '+p.ctx.unit+'.', ok:true},
        {t:'It is $'+p.b+' no matter what.', ok:false},
        {t:'The total is always $'+p.m+'.', ok:false},
        {t:'It takes '+p.m+' '+p.ctx.unit+'s.', ok:false}
      ]);
      P.meaning=opts;
      var mc='<div class="pmc"><div class="tiny" style="margin-top:8px"><b>What does the slope mean here?</b></div>';
      opts.forEach(function(o,i){ mc+='<label class="pmcopt"><input type="radio" name="pmean" value="'+i+'"> '+o.t+'</label>'; });
      mc+='</div>';
      ans.innerHTML=numInputs()+mc;
    }
    draw();
  }

  function drawPracticeCanvas(m,b){
    var p=P.cur; if(!p) return;
    if(p.type==='A'){
      drawLineFor(p.m,p.b,'#8c4fa8',false);                 // the line to read (purple)
      if(P.answered){ drawSlopeTriangle(p.m,p.b); drawIntercept(p.b); }
    } else if(p.type==='B'){
      drawLineFor(m,b,'#2F63E0',false);                     // his line, as he builds it
      drawSlopeTriangle(m,b); drawIntercept(b);
    } else {                                                 // D — show the answer only on reveal
      if(P.answered){ drawLineFor(p.m,p.b,'#8c4fa8',false); drawSlopeTriangle(p.m,p.b); drawIntercept(p.b); }
    }
  }

  function recordResult(type, ok){
    P.byType[type].n++; if(ok){ P.byType[type].ok++; P.solved++; }
  }

  function updateStats(){
    document.getElementById('pstreak').textContent='🔥 streak '+P.streak;
    document.getElementById('psolved').textContent='solved '+P.solved;
    var names={A:'Read graph', B:'Graph it', D:'Word problem'};
    var html='';
    ['A','B','D'].forEach(function(t){ var s=P.byType[t];
      html+='<span class="pbadge">'+names[t]+' '+s.ok+'/'+s.n+'</span> '; });
    document.getElementById('pmastery').innerHTML=html;
  }

  function maybeLevelUp(fb){
    if(P.streak>=3 && P.level<4){
      P.level++; P.streak=0;
      document.getElementById('plevel').value=P.level;
      fb.innerHTML+=' 🎉 <b>Level '+P.level+'!</b> The problems get a bit harder now.';
    }
  }

  function checkAnswer(){
    var p=P.cur; if(!p||P.answered) return;
    var fb=document.getElementById('pfeedback'); fb.style.display='block';
    var ok=false, msg='';
    if(p.type==='B'){
      var m=parseFloat(mEl.value), b=parseFloat(bEl.value);
      ok = near(m,p.m) && near(b,p.b);
      if(!ok){
        var parts=[];
        if(!near(b,p.b)) parts.push('the start should be <b>'+nice(p.b)+'</b> (you have '+nice(b)+')');
        if(!near(m,p.m)) parts.push('the slope should be <b>'+nice(p.m)+'</b> (you have '+nice(m)+')');
        msg='Not yet — '+parts.join(', ')+'. It’s <b>y = '+fmtPlain(p.m,p.b)+'</b>.';
      }
    } else {
      var am=(document.getElementById('pm')||{}).value;
      var ab=(document.getElementById('pb')||{}).value;
      var eqOk = near(am,p.m) && near(ab,p.b);
      var meanOk=true;
      if(p.type==='D'){
        var sel=document.querySelector('input[name=pmean]:checked');
        meanOk = !!(sel && P.meaning[parseInt(sel.value)].ok);
      }
      ok = eqOk && meanOk;
      if(!eqOk){
        if(p.type==='D') msg='The $/'+p.ctx.unit+' is the <b>slope</b> ('+nice(p.m)
          +'); the amount before you do anything is the <b>y-intercept</b> ('+nice(p.b)
          +'). So y = <b>'+fmtPlain(p.m,p.b)+'</b>.';
        else msg='Slope = rise ÷ run — from the y-intercept, right 1 then count up/down. '
          +'It crosses the y-axis at <b>'+nice(p.b)+'</b>. So y = <b>'+fmtPlain(p.m,p.b)+'</b>.';
      } else if(!meanOk){
        msg='The equation is right! But the <b>slope</b> is the rate — <b>$'+nice(p.m)
          +' per '+p.ctx.unit+'</b>. The $'+nice(p.b)+' is the starting amount (the y-intercept).';
      }
    }
    recordResult(p.type, ok);
    if(ok){ fb.innerHTML='✅ <b>Correct!</b>'; P.answered=true; P.streak++; maybeLevelUp(fb); }
    else  { fb.innerHTML='❌ '+msg; P.streak=0; }
    updateStats();
  }

  function showMe(){
    var p=P.cur; if(!p) return;
    P.answered=true;
    mEl.value=p.m; bEl.value=p.b; clamp(mEl); clamp(bEl);
    var pm=document.getElementById('pm'), pb=document.getElementById('pb');
    if(pm) pm.value=nice(p.m); if(pb) pb.value=nice(p.b);
    var fb=document.getElementById('pfeedback'); fb.style.display='block';
    fb.innerHTML='👀 Here it is: <b>y = '+fmtPlain(p.m,p.b)+'</b> — slope <b>'+nice(p.m)
      +'</b>, starts at <b>'+nice(p.b)+'</b>. See it on the graph.';
    draw();
  }

  function nextProblem(){
    P.level=parseInt(document.getElementById('plevel').value)||P.level;
    P.cur=genProblem(P.level); P.answered=false;
    mEl.value=1; bEl.value=0;   // neutral start so type B actually has to be built
    renderProblem(); updateStats();
  }

  function setMode(nm){
    mode=nm;
    document.getElementById('modeExplore').classList.toggle('active', nm==='explore');
    document.getElementById('modePractice').classList.toggle('active', nm==='practice');
    document.getElementById('exploreExtras').style.display = nm==='explore'?'':'none';
    document.getElementById('practiceCard').style.display = nm==='practice'?'':'none';
    if(nm==='practice' && !P.cur){ nextProblem(); }
    draw();
  }

  mEl.addEventListener('input',draw); bEl.addEventListener('input',draw);
  document.getElementById('mdown').onclick=function(){step(mEl,-1);};
  document.getElementById('mup').onclick=function(){step(mEl,1);};
  document.getElementById('bdown').onclick=function(){step(bEl,-1);};
  document.getElementById('bup').onclick=function(){step(bEl,1);};
  document.getElementById('newline').onclick=newTarget;
  document.getElementById('hintbtn').onclick=showHint;
  document.getElementById('modeExplore').onclick=function(){setMode('explore');};
  document.getElementById('modePractice').onclick=function(){setMode('practice');};
  document.getElementById('pcheck').onclick=checkAnswer;
  document.getElementById('pshow').onclick=showMe;
  document.getElementById('pnext').onclick=nextProblem;
  document.getElementById('plevel').onchange=nextProblem;
  window.addEventListener('resize',sizeCanvas);
  // Re-fit the frame whenever the content height changes (mode switch, a new
  // problem, a hint expanding) so there's never an inner scrollbar.
  try{ new ResizeObserver(fitFrame).observe(document.body); }catch(e){}

  buildMissions();
  newTarget();
  sizeCanvas();
  setTimeout(fitFrame, 60);   // after fonts/layout settle
})();
</script>
</body>
</html>"""


def slope_intercept_explorer_html() -> str:
    """The full, static HTML document for the explorer -- returned on its own so
    it can be asserted against in tests without a live Streamlit runtime."""
    return _EXPLORER_HTML


# --- "Find the gap": a quick diagnostic that pinpoints the stuck rung ----------
#
# "Graphing proportional relationships and intercepts" is a stack of sub-skills;
# when a kid is "just struggling," it's usually ONE rung that's shaky. This is a
# 5-question flashlight -- not graded, no score -- that tells the parent which
# rung to aim at instead of re-teaching the whole stack. Fixed questions, so it
# needs no model call.

# Each rung the diagnostic can flag, in teaching order, with the Explorer mission
# (or move) that practices it -- shown in the readout as "start here."
_RUNGS = {
    "plotting": ("Plotting points", "placing (x, y) on the grid"),
    "unit_rate": ("Unit rate / constant", "how much y changes per 1 step of x"),
    "proportional": ("Proportional = through the origin",
                     'the "through (0,0)" fingerprint'),
    "slope": ("Slope as the rate", "rise over run = the unit rate"),
    "intercept": ("The y-intercept", "where the line starts when x = 0"),
}

# question, options, index of the right one, the rung it tests, a nudge for a miss.
DIAGNOSTIC: list[dict] = [
    {
        "q": "Where on a graph is the point (4, 1)?",
        "options": ["4 to the right, then 1 up", "1 to the right, then 4 up",
                    "4 up, then 1 to the right", "4 to the left, then 1 up"],
        "correct": 0, "rung": "plotting",
        "hint": "Points come first across (x), then up (y). Play with reading the "
                "grid before graphing whole lines.",
    },
    {
        "q": "A table reads: x = 2 → y = 6, x = 3 → y = 9, x = 4 → y = 12. "
             "How much does y go up each time x goes up by 1?",
        "options": ["3", "6", "2", "1"],
        "correct": 0, "rung": "unit_rate",
        "hint": "That steady jump is the unit rate (the constant). In the Explorer, "
                "the steepness slider IS this number.",
    },
    {
        "q": "Which line shows a PROPORTIONAL relationship?",
        "options": ["A straight line through the corner (0, 0)",
                    "A straight line that crosses the y-axis at 4",
                    "A curve that bends", "A flat line at y = 5"],
        "correct": 0, "rung": "proportional",
        "hint": "Proportional lines always pass through (0, 0). Try the Explorer "
                'mission "make it go through the corner."',
    },
    {
        "q": "A line goes UP 2 every time it goes 1 to the RIGHT. What is its slope?",
        "options": ["2", "1/2", "1", "3"],
        "correct": 0, "rung": "slope",
        "hint": "Slope = rise ÷ run = up over right. Watch the red triangle in the "
                "Explorer as you drag the steepness slider.",
    },
    {
        "q": "Where does the line y = 3x + 5 cross the y-axis?",
        "options": ["(0, 5)", "(5, 0)", "(0, 3)", "(0, 0)"],
        "correct": 0, "rung": "intercept",
        "hint": 'The "+ 5" is where it starts (x = 0). In the Explorer, drag the '
                '"where it starts" slider and watch that point.',
    },
]


def _diagnostic_readout(answers: list[int | None]) -> dict:
    """Turn the five picks into {shaky: [rung_key...], got: [...], all_right: bool}
    in teaching order -- the lowest shaky rung is where to start."""
    shaky, got = [], []
    for q, picked in zip(DIAGNOSTIC, answers):
        (shaky if picked != q["correct"] else got).append(q["rung"])
    # de-dup while keeping _RUNGS' teaching order
    order = list(_RUNGS)
    shaky = sorted(set(shaky), key=order.index)
    got = sorted(set(got), key=order.index)
    return {"shaky": shaky, "got": got, "all_right": not shaky}


# --- the scaffolded 6-lesson ladder (built on the existing series machinery) ---
#
# A fixed day-by-day plan that walks the exact rungs the Math graph lists. Passed
# straight to the Math agent's generate_series as the `plan`, so each day is a
# normal, graded Compass lesson -- we only pin the sequence, the agent writes the
# content. Lands in the Backlog to schedule by day.
GRAPHING_LADDER: list[dict[str, str]] = [
    {"title": "Plot points fast",
     "focus": "Plot and name points (x, y) on the coordinate plane — reading and "
              "placing ordered pairs fluently, across first then up. Just the grid "
              "mechanics, so graphing lines later isn't slowed by point-plotting."},
    {"title": "Unit rate from a table",
     "focus": "Find the unit rate / constant of proportionality from a real-world "
              "table (e.g. $3 per taco): how much y goes up for each 1 increase in "
              "x, and writing it as y = kx."},
    {"title": "Proportional graphs go through the origin",
     "focus": "Plot a proportional table and see it forms a straight line through "
              "(0, 0). Connect the table's constant ratio to y = kx and to the "
              "steepness of the line; recognize the through-the-origin fingerprint "
              "of a proportional relationship."},
    {"title": "Slope is the rate",
     "focus": "Slope as rise over run on a graph, and that it equals the unit rate "
              "— the SAME number in the table, the graph's steepness, and the k in "
              "y = kx. Compute slope from a graph and from two points."},
    {"title": "When it doesn't start at zero: the y-intercept",
     "focus": "Introduce y = mx + b by contrast with proportional — a line that "
              "starts at (0, b) instead of the origin (e.g. a $5 flat fee plus $3 "
              "per taco). Identify and interpret b as the starting value; put "
              "proportional and non-proportional graphs side by side."},
    {"title": "Read a graph, write the equation",
     "focus": "Given a graph or a drawn line, read off the slope (m) and the "
              "y-intercept (b) and write y = mx + b. Mixed practice reading graphs "
              "backwards into equations, both proportional (b = 0) and not."},
]


def _ladder_proposal():
    """A hand-built proposal for the graphing ladder -- heavy scaffolding, a
    concrete real-world story, and a pointer to the Explorer, for a student who
    was stuck on exactly this."""
    from compass.agents.framework import TopicProposal

    return TopicProposal(
        topic="Graphing proportional relationships, slope & y-intercepts",
        rationale="A scaffolded ladder for a student who was struggling with "
                  "graphing proportional relationships and reading intercepts.",
        strategy="parent_graphing_ladder",
        guidance=(
            "This student is STRUGGLING with this topic — scaffold heavily. Anchor "
            "every day in ONE concrete real-world story (money, speed, a recipe) and "
            "show the same relationship as a table, a graph, and an equation so the "
            "connections are explicit. Keep numbers friendly. Point him to the "
            "in-app “Slope & Intercept Explorer” (Graphing page) to try each idea "
            "hands-on."
        ),
        context_lines=[
            "The student has been struggling with graphing proportional "
            "relationships and reading y-intercepts.",
            "There is an interactive “Slope & Intercept Explorer” in the app "
            "(the Graphing page) he can use alongside these lessons.",
        ],
    )


# A close starting height so the first paint doesn't clip before the widget
# auto-fits its own frame to its content (see fitFrame in the JS). After that the
# frame grows/shrinks to exactly fit -- no inner scrollbar, whichever mode he's in.
EXPLORER_HEIGHT = 980


def render_graph_explorer() -> None:
    """Drop the Slope & Intercept Explorer onto the page (a components iframe).

    `scrolling` stays on only as a safety net: the page self-sizes its own iframe
    to its content (fitFrame), so in practice no inner scrollbar ever shows -- the
    whole tool stays in view and the page scrolls as one."""
    import streamlit.components.v1 as components

    components.html(_EXPLORER_HTML, height=EXPLORER_HEIGHT, scrolling=True)


def render_graphing_diagnostic(db, student) -> None:
    """The 5-question "find the gap" check: a quick flashlight on which rung is
    shaky. Not graded; it just steers the parent (and the Explorer) at the right
    spot. Its result is remembered so it survives the reruns around it."""
    import streamlit as st

    st.markdown("#### 🔎 Find the gap — a quick 5-question check")
    st.caption(
        "Not a test — it just shows which step is shaky, so you aim at that instead "
        "of re-teaching everything. Have him answer honestly."
    )
    with st.form("graph_diag"):
        picks: list = []
        for i, q in enumerate(DIAGNOSTIC):
            picks.append(
                st.radio(f"**{i + 1}. {q['q']}**", q["options"],
                         index=None, key=f"gd_{i}")
            )
        submitted = st.form_submit_button("See where he's stuck", type="primary")

    if submitted:
        if any(p is None for p in picks):
            st.warning("Answer all five first.")
        else:
            idx = [q["options"].index(p) for q, p in zip(DIAGNOSTIC, picks)]
            st.session_state["graph_diag_result"] = _diagnostic_readout(idx)

    result = st.session_state.get("graph_diag_result")
    if not result:
        return

    st.divider()
    if result["all_right"]:
        st.success(
            "🎉 He's got all the pieces — the struggle is likely **putting them "
            "together**, not a missing skill. Have him play the **“match the mystery "
            "line”** game above and do a few mixed problems reading graphs into "
            "equations."
        )
    else:
        names = ", ".join(_RUNGS[r][0] for r in result["shaky"])
        st.markdown(f"**👉 Start here:** {names}")
        for r in result["shaky"]:
            title, _ = _RUNGS[r]
            hint = next(q["hint"] for q in DIAGNOSTIC if q["rung"] == r)
            st.markdown(f"- **{title}** — {hint}")
        if result["got"]:
            st.caption(
                "Already solid: " + ", ".join(_RUNGS[r][0] for r in result["got"]) + "."
            )
        st.caption(
            "The **6-lesson ladder** below builds these up in order, or use the "
            "Explorer's missions for just the shaky ones."
        )
    if st.button("↺ Retake the check", key="gd_retake"):
        for i in range(len(DIAGNOSTIC)):
            st.session_state.pop(f"gd_{i}", None)
        st.session_state.pop("graph_diag_result", None)
        st.rerun()


_MISSIONS_CARD_NOTE = (
    "Open the 📈 Graphing page, then tap the 🎓 Practice tab.\n\n"
    "Your goal today: get a 🔥 streak of 3 in a row and level up at least once.\n"
    "Work the three problem kinds:\n"
    "• Read graph — read the purple line and type its equation (slope + y-intercept).\n"
    "• Graph it — dial the sliders to match the equation it gives you.\n"
    "• Word problem — write the equation, and pick what the slope means.\n\n"
    "Stuck? Tap 👀 Show me to see the answer on the graph, then try the next one. "
    "When you've leveled up, turn this card in.\n\n"
    "(Warm-up option: the Explore tab's Missions + Mystery Line Challenge.)"
)


def render_graphing_missions_card(db, student) -> None:
    """Parent-only: drop a trackable card on his board for the Explorer missions.
    He works them here, turns the card in, and it logs the time (and a little XP) --
    so the hands-on practice counts like everything else. Reported: "set this up
    with some missions that can be cards." Rides the general-card path."""
    import streamlit as st

    from datetime import date

    from compass.agents import khan_card

    st.markdown("#### 🎯 Put graphing practice on his board")
    st.caption(
        "Adds one card for a round of **Practice** (and the warm-up missions) — a "
        "short, repeatable rep he does right here. Turning it in logs the time and a "
        "little XP, so it's tracked like everything else. Defaults to **today**."
    )
    with st.expander("What the card asks him to do"):
        st.markdown(_MISSIONS_CARD_NOTE)
    cols = st.columns([2, 1])
    day = cols[0].date_input("Assign to", value=date.today(), key="gm_day")
    to_backlog = cols[1].checkbox("Backlog instead", key="gm_backlog")
    if st.button("➕ Add today's graphing-practice card", key="gm_add", type="primary"):
        khan_card.create_khan_card(
            db, student, subject="math",
            unit="📈 Graphing practice — Slope & Intercept Explorer",
            note=_MISSIONS_CARD_NOTE, minutes=15,
            day_iso=None if to_backlog else day.isoformat(),
            quiz=[], generate_quiz=False, general_card=True, xp_override=15,
        )
        where = "the Backlog" if to_backlog else day.strftime("%a %b %-d")
        st.success(
            f"✅ Added a graphing-practice card to {where}. He opens the Graphing page, "
            "does a round of Practice, then turns it in."
        )


def render_graphing_ladder_builder(db, student, *, api_ok: bool) -> None:
    """Parent-only: one click builds the fixed 6-lesson graphing ladder into the
    Backlog, each day written as a normal graded Math lesson by the Math agent."""
    import streamlit as st

    from compass import config
    from compass.agents import LessonGenerationError, get_agent

    st.markdown("#### 📚 Put it on his schedule — the 6-lesson graphing ladder")
    st.caption(
        "Builds six day-sized Math lessons — one per rung, in order — into the "
        "Board's **Backlog** for you to assign by day. Each is a full graded lesson "
        "that points back to the Explorer."
    )
    with st.expander("See the six rungs"):
        for i, day in enumerate(GRAPHING_LADDER, 1):
            st.markdown(f"**{i}. {day['title']}** — {day['focus']}")

    if st.button(
        "✍️ Build the 6-lesson ladder → Backlog",
        type="primary", disabled=not api_ok, key="build_graph_ladder",
    ):
        from compass.ui import context_for  # lazy: avoids an import cycle

        agent = get_agent("math")
        minutes = config.SUBJECT_DEFAULT_MINUTES.get("math", 60)
        ctx = context_for(db, student, minutes=minutes)
        with st.spinner("Writing six scaffolded graphing lessons…"):
            try:
                results = agent.generate_series(ctx, _ladder_proposal(), plan=GRAPHING_LADDER)
            except LessonGenerationError as exc:
                st.error(str(exc))
                return
        st.success(
            f"✅ Built {len(results)} lessons into the Backlog. Assign them by day "
            "from **Mission Control → Board**."
        )
        for r in results:
            st.caption("• " + (r.payload.get("title") or "Lesson"))
    if not api_ok:
        st.caption("⚠️ Add an API key (Student Profile) to generate the lessons.")
