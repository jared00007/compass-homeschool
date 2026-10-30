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


# Tall enough that the two columns show without the iframe clipping on a narrow
# (stacked) layout; the widget lays itself out responsively inside.
EXPLORER_HEIGHT = 900


def render_graph_explorer() -> None:
    """Drop the Slope & Intercept Explorer onto the page (a components iframe)."""
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
