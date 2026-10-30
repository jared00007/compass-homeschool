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
    padding:14px 16px;box-shadow:0 2px 0 rgba(46,94,170,.15);}
  canvas{width:100%;height:auto;display:block;border-radius:8px;}
  h2{font-size:17px;margin:0 0 4px;}
  .sub{color:var(--dim);font-size:13px;margin:0 0 10px;}
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
  .missions li{display:flex;align-items:center;gap:9px;padding:7px 4px;
    border-bottom:1px dashed var(--grid-strong);font-size:14px;}
  .missions li:last-child{border-bottom:none;}
  .chk{flex:0 0 22px;height:22px;border-radius:50%;border:2px solid var(--grid-strong);
    display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;color:#fff;}
  .missions li.done .chk{background:var(--good);border-color:var(--good);}
  .missions li.done{color:var(--good);font-weight:700;}
  .match{margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
  .match .status{font-weight:800;}
  .btn{border:2px solid var(--border);background:var(--accent);color:var(--ink);
    font-weight:800;font-size:14px;padding:8px 12px;border-radius:9px;cursor:pointer;}
  .btn:active{transform:translateY(1px);}
  .legend{font-size:12px;color:var(--dim);margin-top:8px;}
  .legend b.l{color:var(--line);} .legend b.t{color:var(--accent);}
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
  </div>

  <!-- Right: controls, equation, table, missions -->
  <div class="col">
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
        <tbody><tr><th>y</th><td id="y0">0</td><td id="y1">1</td><td id="y2">2</td><td id="y3">3</td><td id="y4">4</td></tr></tbody>
      </table>
      <div class="tiny">Notice: each step right, y jumps by the slope.</div>
    </div>

    <div class="card" style="margin-top:14px;">
      <h2>🎯 Missions</h2>
      <p class="sub">Dial the line to make each one true.</p>
      <ul id="missions" class="missions"></ul>

      <div class="match">
        <span>Last one — <b>match the dashed mystery line</b>:</span>
        <span id="matchstatus" class="status" style="color:var(--dim)">keep trying…</span>
        <button id="newline" class="btn">🎲 New mystery line</button>
        <span id="matchcount" class="tiny"></span>
      </div>
    </div>
  </div>
</div>

<script>
(function(){
  var XMIN=-10, XMAX=10, YMIN=-10, YMAX=10;
  var cv = document.getElementById('grid');
  var ctx = cv.getContext('2d');
  var mEl=document.getElementById('m'), bEl=document.getElementById('b');
  var target = null, matches = 0;

  function sizeCanvas(){
    var cssW = cv.clientWidth || 460;
    var dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(cssW*dpr);
    cv.height = Math.round(cssW*dpr); // square
    ctx.setTransform(dpr,0,0,dpr,0,0);
    draw();
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
    ctx.fillText((m>0?'up ':'down ')+nice(Math.abs(m)), px(1)+4, py(b+m/2));
    ctx.restore();
  }

  function drawIntercept(b){
    ctx.save();
    ctx.fillStyle='#F2B705'; ctx.strokeStyle='#241C12'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.arc(px(0),py(b),7,0,7); ctx.fill(); ctx.stroke();
    ctx.fillStyle='#241C12'; ctx.font='bold 12px sans-serif';
    // Label sits to the LEFT of the y-axis so it never collides with the slope
    // triangle's "right 1 / up N" labels, which run off to the right.
    ctx.textAlign='right'; ctx.textBaseline='bottom';
    ctx.fillText('(0, '+nice(b)+')', px(0)-10, py(b)-6);
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

  function newTarget(){
    var ms=[-3,-2,-1,-0.5,0.5,1,2,3];
    var m=ms[Math.floor(Math.random()*ms.length)];
    var b=Math.floor(Math.random()*13)-6; // -6..6
    target={m:m,b:b};
    document.getElementById('matchstatus').textContent='keep trying…';
    document.getElementById('matchstatus').style.color='#8A7A5E';
    draw();
  }

  function draw(){
    var m=parseFloat(mEl.value), b=parseFloat(bEl.value);
    drawGrid();
    if(target) drawLineFor(target.m,target.b,'#9AA0A6',true);
    drawLineFor(m,b,'#2F63E0',false);
    drawSlopeTriangle(m,b);
    drawIntercept(b);

    document.getElementById('mval').textContent=nice(m);
    document.getElementById('bval').textContent=nice(b);
    document.getElementById('eq').innerHTML=fmtEq(m,b);
    for(var i=0;i<=4;i++){ document.getElementById('y'+i).textContent=nice(m*i+b); }

    var badge=document.getElementById('badge');
    if(b===0){ badge.className='badge prop';
      badge.innerHTML='✓ Proportional — it goes through the corner (0, 0)'; }
    else{ badge.className='badge notprop';
      badge.innerHTML='Not proportional — it starts at (0, '+nice(b)+'), not the corner'; }

    MISSIONS.forEach(function(ms,i){
      document.getElementById('mi'+i).classList.toggle('done', ms.test(m,b));
    });

    if(target){
      var hit = Math.abs(m-target.m)<1e-9 && Math.abs(b-target.b)<1e-9;
      var st=document.getElementById('matchstatus');
      if(hit){ st.textContent='✓ Matched! 🎉'; st.style.color='#2F9B68';
        if(!target.counted){ target.counted=true; matches++;
          document.getElementById('matchcount').textContent='matched: '+matches; } }
      else{ st.textContent='keep trying…'; st.style.color='#8A7A5E'; }
    }
  }

  function clamp(el){ var v=parseFloat(el.value),
    lo=parseFloat(el.min), hi=parseFloat(el.max);
    el.value=Math.max(lo,Math.min(hi,v)); }
  function step(el,dir){ el.value=parseFloat(el.value)+dir*parseFloat(el.step);
    clamp(el); draw(); }

  mEl.addEventListener('input',draw); bEl.addEventListener('input',draw);
  document.getElementById('mdown').onclick=function(){step(mEl,-1);};
  document.getElementById('mup').onclick=function(){step(mEl,1);};
  document.getElementById('bdown').onclick=function(){step(bEl,-1);};
  document.getElementById('bup').onclick=function(){step(bEl,1);};
  document.getElementById('newline').onclick=newTarget;
  window.addEventListener('resize',sizeCanvas);

  buildMissions();
  newTarget();
  sizeCanvas();
})();
</script>
</body>
</html>"""


def slope_intercept_explorer_html() -> str:
    """The full, static HTML document for the explorer -- returned on its own so
    it can be asserted against in tests without a live Streamlit runtime."""
    return _EXPLORER_HTML


# Tall enough that the two columns show without the iframe clipping on a narrow
# (stacked) layout; the widget lays itself out responsively inside.
EXPLORER_HEIGHT = 900


def render_graph_explorer() -> None:
    """Drop the Slope & Intercept Explorer onto the page (a components iframe)."""
    import streamlit.components.v1 as components

    components.html(_EXPLORER_HTML, height=EXPLORER_HEIGHT, scrolling=True)
