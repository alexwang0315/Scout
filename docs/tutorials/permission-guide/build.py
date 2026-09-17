#!/usr/bin/env python3
"""Generate the offline Permission teaching deck from reviewed data and screenshots."""
from pathlib import Path
import base64,html,json,hashlib
ROOT=Path(__file__).resolve().parent
DATA=json.loads((ROOT/'slides.json').read_text())
from verify_ui_sync import Verifier
capture_check=Verifier(ROOT,ROOT.parents[2],True).run()
if capture_check['errors']:
    raise SystemExit('Recapture changed UI: '+str(capture_check['errors']))
CAPTURES={shot['page_id']:shot for shot in json.loads((ROOT/'capture-sources.json').read_text())['shots']}
esc=lambda v:html.escape(str(v),quote=True)
CSS=r"""
html,body{height:100%;overflow-x:hidden;margin:0}html{scroll-snap-type:y mandatory;scroll-behavior:smooth}
.slide{width:100vw;height:100vh;height:100dvh;overflow:hidden;scroll-snap-align:start;display:flex;flex-direction:column;position:relative}
.slide-content{flex:1;display:flex;flex-direction:column;justify-content:center;max-height:100%;overflow:hidden;padding:var(--slide-padding)}
:root{--title-size:clamp(1.5rem,5vw,4rem);--h2-size:clamp(1.25rem,3.5vw,2.5rem);--h3-size:clamp(1rem,2.5vw,1.75rem);--body-size:clamp(.75rem,1.5vw,1.125rem);--small-size:clamp(.65rem,1vw,.875rem);--slide-padding:clamp(1rem,4vw,4rem);--content-gap:clamp(.5rem,2vw,2rem);--element-gap:clamp(.25rem,1vw,1rem)}
.card,.container,.content-box{max-width:min(90vw,1000px);max-height:min(80vh,700px)}
.feature-list,.bullet-list{gap:clamp(.4rem,1vh,1rem)}.feature-list li,.bullet-list li{font-size:var(--body-size);line-height:1.4}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:clamp(.5rem,1.5vw,1rem)}
img,.image-container{max-width:100%;max-height:min(50vh,400px);object-fit:contain}
@media(max-height:700px){:root{--slide-padding:clamp(.75rem,3vw,2rem);--content-gap:clamp(.4rem,1.5vw,1rem);--title-size:clamp(1.25rem,4.5vw,2.5rem);--h2-size:clamp(1rem,3vw,1.75rem)}}
@media(max-height:600px){:root{--slide-padding:clamp(.5rem,2.5vw,1.5rem);--content-gap:clamp(.3rem,1vw,.75rem);--title-size:clamp(1.1rem,4vw,2rem);--body-size:clamp(.7rem,1.2vw,.95rem)}.nav-dots,.keyboard-hint,.decorative{display:none}}
@media(max-height:500px){:root{--slide-padding:clamp(.4rem,2vw,1rem);--title-size:clamp(1rem,3.5vw,1.5rem);--h2-size:clamp(.9rem,2.5vw,1.25rem);--body-size:clamp(.65rem,1vw,.85rem)}}
@media(max-width:600px){:root{--title-size:clamp(1.25rem,7vw,2.5rem)}.grid{grid-template-columns:1fr}}
/* Scout field guide: intentional CJK fallbacks keep the standalone file portable. */
:root{--forest:#142d26;--deep:#0c211c;--paper:#f4f1e6;--ink:#183c32;--muted:#51665e;--line:#cad1c3;--lime:#d6ef92;--pad:clamp(18px,3.6vw,72px);--small:clamp(12px,.95vw,17px);--footer:clamp(52px,6vh,66px)}
*{box-sizing:border-box}body{overflow:visible;background:var(--deep);color:var(--ink);font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei","Droid Sans Fallback",sans-serif}
button,select,a{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible,select:focus-visible{outline:3px solid #dd9e2d;outline-offset:4px}
.slide{padding:clamp(18px,3vh,42px) var(--pad) calc(var(--footer) + clamp(22px,2.8vh,36px));gap:clamp(12px,2vh,28px);background:var(--paper);border-top:clamp(4px,.5vh,7px) solid var(--forest)}
.slide:before{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(90deg,transparent 0 4.9vw,#153a2b05 4.9vw 5vw)}
.slide>*{position:relative}.header{flex-shrink:0}
.eyebrow{font-size:var(--small);font-weight:700;letter-spacing:.12em;display:flex;align-items:center;gap:clamp(12px,1.4vw,24px);color:var(--muted);margin-bottom:clamp(8px,1.3vh,18px)}
.wordmark{font-family:Georgia,serif;color:var(--ink);font-size:clamp(16px,1.2vw,22px);letter-spacing:.18em}
h1,h2,h3,p{margin:0}h2{font-size:clamp(25px,3.05vw,54px);line-height:1.25;letter-spacing:-.035em;font-weight:750;max-width:96%}
.lead{font-size:clamp(16px,1.45vw,26px);color:var(--muted);margin-top:clamp(10px,1.5vh,20px);line-height:1.5;max-width:96%}
.content{flex:1;min-height:0}.body-grid{display:grid;grid-template-columns:.84fr 1.2fr;align-items:center;gap:clamp(20px,3vw,54px);height:100%;min-height:0}
.steps{display:grid;gap:clamp(14px,2.5vh,34px);align-content:center;min-width:0}
.step{display:grid;grid-template-columns:clamp(28px,2.5vw,42px) 1fr;gap:clamp(10px,1.1vw,20px);min-width:0}
.step-number{font-family:Georgia,serif;font-size:clamp(18px,1.8vw,32px);line-height:1.2;color:#6c806d;border-top:2px solid #bdc8b5;padding-top:clamp(6px,.6vh,10px)}
.step h3{font-size:clamp(16px,1.53vw,28px);line-height:1.45;overflow-wrap:anywhere}
.step p{font-size:clamp(15px,1.18vw,21px);line-height:1.6;color:var(--muted);margin-top:clamp(4px,.5vh,8px)}
.screen-figure{margin:0;min-height:0;max-height:100%;display:flex;flex-direction:column;gap:clamp(8px,1vh,14px)}
.shot-button{display:block;border:1px solid #abc1ad;background:#d6ddce;padding:clamp(5px,.65vw,10px);width:100%;min-height:0;box-shadow:0 10px 30px #14332812;border-radius:clamp(6px,.7vw,12px)}
.shot-button img{display:block;width:100%;max-height:54vh;object-fit:contain;object-position:top}
figcaption{font-size:var(--small);color:var(--muted);line-height:1.5}.zoom-hint{display:block;color:var(--ink);font-weight:600}
.card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:clamp(14px,2vw,30px);height:100%;align-content:center}
.guide-card{border:1px solid #aebaab;background:#fcfaf3;padding:clamp(18px,2vw,38px);border-radius:clamp(8px,.8vw,14px);text-align:left;color:var(--ink);display:flex;flex-direction:column;gap:clamp(12px,1.7vh,24px);min-width:0;min-height:0}
button.guide-card:hover{background:#e6efcf;border-color:#658464}.guide-card h3{font-size:clamp(21px,2.2vw,38px);line-height:1.3}
.guide-card p{font-size:clamp(16px,1.5vw,26px);line-height:1.55;color:var(--muted)}.card-tag{font-size:clamp(13px,1vw,18px);color:#466949;border-top:1px solid var(--line);padding-top:clamp(10px,1.1vh,18px);font-weight:600}
.flow .steps,.finish .steps{grid-template-columns:repeat(2,minmax(0,1fr));gap:clamp(24px,4vh,55px) clamp(24px,5vw,80px);height:100%}
.flow .step,.finish .step{background:#fcfaf3;padding:clamp(16px,2vw,34px);border-top:1px solid #a5b99b;border-radius:clamp(7px,.7vw,12px)}
.flow .step h3,.finish .step h3{font-size:clamp(19px,1.9vw,34px)}.flow .step p,.finish .step p{font-size:clamp(15px,1.4vw,25px)}
.takeaway{flex-shrink:0;font-size:clamp(16px,1.4vw,25px);line-height:1.5;background:#dfebcb;border-left:clamp(4px,.4vw,7px) solid #7a935b;padding:clamp(10px,1.4vh,20px) clamp(14px,1.5vw,26px)}
.example .body-grid{grid-template-columns:1fr 1fr}.example-box{background:var(--forest);color:var(--paper);border-radius:clamp(8px,1vw,18px);padding:clamp(22px,3vw,48px);font-size:clamp(22px,2.2vw,39px);line-height:1.8;white-space:pre-wrap;border-bottom:clamp(5px,.7vh,9px) solid #d6d1a4}
.example-label{display:block;font-size:var(--small);color:var(--lime);margin-bottom:clamp(12px,2vh,24px)}
.status-grid{display:grid;gap:clamp(12px,2vh,28px);height:100%;align-content:center}
.status-row{display:grid;grid-template-columns:.85fr 1.5fr;gap:clamp(16px,3vw,48px);align-items:center;background:#fcfaf3;padding:clamp(15px,2vh,30px) clamp(18px,2vw,36px);border-left:clamp(4px,.5vw,8px) solid #b1ce8b;border-bottom:1px solid var(--line)}
.status-row.amber{border-left-color:#c7973d}.status-row.red{border-left-color:#bd7762}.status-row h3{font-size:clamp(16px,1.5vw,28px);line-height:1.4;overflow-wrap:anywhere}.status-row p{font-size:clamp(16px,1.4vw,25px);line-height:1.6;color:var(--muted)}
.cover{background:var(--forest);color:var(--paper);border-top-color:var(--lime);justify-content:center}
.cover .eyebrow{color:#aec5b2;margin-bottom:clamp(34px,6vh,80px)}.cover .wordmark{color:var(--lime)}
.cover h1{font-size:clamp(32px,4.5vw,80px);letter-spacing:-.04em;line-height:1.15}.cover h2{font-size:clamp(36px,5.2vw,96px);color:var(--lime);max-width:80%;margin-top:clamp(18px,3vh,42px)}
.cover .tagline{font-size:clamp(18px,1.6vw,30px);color:#ced9c9;margin-top:clamp(22px,4vh,56px);line-height:1.6}
.cover .cover-meta{margin-top:clamp(28px,6vh,84px);font-size:clamp(14px,1.1vw,20px);color:#adc4b1}
.contours{position:absolute;right:-17vw;top:-27vh;width:62vw;height:140vh;border:1px solid #cad5a32b;border-radius:44%;transform:rotate(-24deg);box-shadow:0 0 0 4vw #ffffff03,0 0 0 4.05vw #cad5a321,0 0 0 8vw #ffffff02,0 0 0 8.05vw #cad5a322,0 0 0 12vw #ffffff01,0 0 0 12.05vw #cad5a31c;pointer-events:none}
.finish{background:#e6eccf}.finish h2{max-width:100%}
.slide-foot{position:absolute;left:var(--pad);right:var(--pad);bottom:calc(var(--footer) + 4px);display:flex;justify-content:space-between;font-size:clamp(11px,.8vw,14px);color:#698069;letter-spacing:.05em}.cover .slide-foot{color:#a1b5a5}
.nav{position:fixed;z-index:50;bottom:0;left:0;right:0;height:var(--footer);display:flex;align-items:center;gap:clamp(8px,1.1vw,18px);padding:0 var(--pad);background:var(--deep);color:var(--paper);border-top:1px solid #4c6651}
.nav button,.nav a,.nav select{background:transparent;color:var(--paper);border:1px solid #557060;border-radius:5px;min-height:clamp(34px,4vh,42px);padding:clamp(4px,.6vh,8px) clamp(9px,1vw,16px);font-size:clamp(13px,1vw,16px);text-decoration:none;white-space:nowrap}
.nav button:disabled{opacity:.35;cursor:default}.nav button:hover:not(:disabled),.nav a:hover{background:#37553c}
.nav select{max-width:clamp(115px,24vw,360px);background:var(--deep)}.nav .index{font-size:clamp(13px,1vw,16px);font-variant-numeric:tabular-nums}.nav .spacer{flex:1}.nav .play{color:var(--lime);border-color:#789057}
.progress{position:fixed;z-index:60;bottom:calc(var(--footer) - 1px);height:3px;background:var(--lime);left:0;transition:width .2s}.keyboard-hint{font-size:clamp(11px,.85vw,14px);color:#b3c1ad}
dialog{border:1px solid #6a8269;border-radius:12px;padding:clamp(12px,2vw,28px);max-width:96vw;max-height:94dvh;background:#eff2e8;color:var(--ink)}dialog::backdrop{background:#06100bd9}
dialog img{display:block;max-width:90vw;max-height:80dvh;object-fit:contain}
dialog .dialog-head{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:clamp(8px,1vh,14px);font-size:clamp(14px,1vw,18px)}
dialog button{background:var(--forest);color:white;border:0;padding:10px 16px;border-radius:5px;font-size:clamp(14px,1vw,18px)}
.reveal{opacity:0;transform:translateY(14px);transition:opacity .35s,transform .35s}.is-visible .reveal{opacity:1;transform:none}
@media(max-width:1000px){.nav .secondary,.keyboard-hint{display:none}.body-grid{grid-template-columns:.95fr 1.05fr;gap:20px}}
@media(max-width:600px) and (min-height:501px){
:root{--footer:56px;--pad:18px}.slide{gap:12px;padding-top:18px;padding-bottom:calc(var(--footer) + 28px)}
.eyebrow{font-size:11px;margin-bottom:8px}.eyebrow .wordmark{font-size:14px}h2{font-size:clamp(25px,6.4vw,34px);max-width:100%}.lead{font-size:15px;line-height:1.45;margin-top:8px;max-width:100%}
.body-grid{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr);gap:12px;align-items:center}
.steps{gap:10px}.step{grid-template-columns:24px 1fr;gap:8px}.step-number{font-size:18px;padding-top:4px}.step h3{font-size:16px;line-height:1.4}.step p{font-size:15px;line-height:1.45;margin-top:2px}
.screen-figure{align-self:end;max-height:100%;gap:5px}.shot-button img{max-height:19vh}.shot-button{padding:4px}figcaption{font-size:11px;line-height:1.35}.zoom-hint{display:inline;margin-left:6px}
.card-grid{gap:10px}.guide-card{padding:13px;gap:10px}.guide-card h3{font-size:21px}.guide-card p{font-size:15px;line-height:1.5}.card-tag{font-size:12px;padding-top:7px}
.flow .steps,.finish .steps{grid-template-columns:1fr;gap:10px;align-content:center}.flow .step,.finish .step{padding:10px 12px}.flow .step h3,.finish .step h3{font-size:17px}.flow .step p,.finish .step p{font-size:15px}
.takeaway{font-size:15px;padding:9px 12px}.status-grid{gap:10px}.status-row{grid-template-columns:1fr;padding:10px 13px;gap:5px}.status-row h3{font-size:16px}.status-row p{font-size:15px;line-height:1.45}
.example .body-grid{grid-template-columns:1fr;grid-template-rows:auto auto;align-content:center}.example-box{font-size:20px;padding:18px;line-height:1.65}.example-label{font-size:12px;margin-bottom:8px}
.nav{gap:6px;padding:0 12px}.nav button,.nav select{font-size:13px;padding:5px 8px}.nav .index,.nav .full{display:none}.nav select{max-width:150px}.nav .spacer{display:none}.nav .play{margin-left:auto}
.slide-foot{font-size:10px}.slide-foot .foot-detail{display:none}.cover h2{max-width:100%;font-size:clamp(38px,11vw,60px)}.cover .tagline{font-size:18px}.cover .cover-meta{font-size:13px}.cover h1{font-size:28px}.contours{opacity:.4}
}
@media(max-height:700px) and (min-width:601px){
.slide{padding-top:18px;gap:14px}.eyebrow{margin-bottom:8px}h2{font-size:clamp(24px,3vw,42px)}.lead{font-size:clamp(15px,1.45vw,21px);margin-top:8px}.steps{gap:14px}.step h3{font-size:clamp(16px,1.5vw,23px)}.step p{font-size:clamp(15px,1.15vw,18px);line-height:1.45}
.guide-card{padding:20px;gap:12px}.guide-card p{font-size:17px}.flow .steps,.finish .steps{gap:18px}.flow .step,.finish .step{padding:18px}.takeaway{font-size:16px;padding:10px 14px}.status-row{padding:14px 18px}.status-row p{font-size:17px}.shot-button img{max-height:48vh}
}
@media(max-height:500px){
:root{--footer:44px;--pad:20px}.slide{padding:12px 20px 68px;gap:10px}.eyebrow{font-size:10px;margin-bottom:5px}.eyebrow .wordmark{font-size:13px}h2{font-size:24px;max-width:100%}.lead{font-size:14px;line-height:1.4;margin-top:5px}
.body-grid{grid-template-columns:1fr 1fr;gap:20px}.steps{gap:8px}.step{grid-template-columns:22px 1fr;gap:7px}.step-number{font-size:17px;padding-top:3px}.step h3{font-size:15px;line-height:1.35}.step p{font-size:14px;line-height:1.4;margin-top:2px}.shot-button img{max-height:40vh}figcaption{font-size:10px}.zoom-hint{display:none}
.guide-card{padding:12px;gap:6px}.guide-card h3{font-size:20px}.guide-card p{font-size:14px;line-height:1.4}.card-tag{font-size:11px;padding-top:5px}.card-grid{gap:10px}
.flow .steps,.finish .steps{gap:10px}.flow .step,.finish .step{padding:10px}.flow .step h3,.finish .step h3{font-size:16px}.flow .step p,.finish .step p{font-size:14px}.takeaway{font-size:14px;padding:7px 10px;line-height:1.4}
.status-grid{gap:8px}.status-row{padding:9px 12px;gap:12px;grid-template-columns:1.2fr 1.5fr}.status-row h3,.status-row p{font-size:14px;line-height:1.4}
.example-box{font-size:20px;padding:16px;line-height:1.6}.example-label{font-size:11px;margin-bottom:8px}
.cover .eyebrow{margin-bottom:18px}.cover h1{font-size:26px}.cover h2{font-size:44px;margin-top:12px}.cover .tagline{font-size:16px;margin-top:16px}.cover .cover-meta{font-size:12px;margin-top:20px}
.nav{padding:0 20px;gap:7px}.nav button,.nav a,.nav select{font-size:12px;min-height:30px;padding:4px 9px}.nav .secondary,.keyboard-hint{display:none}.slide-foot{font-size:10px}
}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.01ms!important;transition-duration:.01ms!important}html{scroll-behavior:auto}.reveal{opacity:1;transform:none}}
@page{size:16in 9in;margin:0}
@media print{html,body{height:auto;overflow:visible;scroll-behavior:auto;background:var(--paper)}.slide{width:16in;height:9in;break-after:page;page-break-after:always;print-color-adjust:exact;-webkit-print-color-adjust:exact;padding-bottom:44px}.slide:last-child{break-after:auto;page-break-after:auto}.nav,.progress,dialog{display:none!important}.reveal{opacity:1!important;transform:none!important}.slide-foot{bottom:16px}.shot-button{box-shadow:none}.zoom-hint{display:none}.cover{justify-content:center}}
"""
CSS+=r"""
.body-grid{grid-template-columns:.76fr 1.3fr;gap:clamp(18px,2.5vw,44px)}
.shot-button{line-height:0}.shot-stage{display:block;position:relative;margin:auto;width:min(100%,calc(49vh * var(--shot-aspect)));max-width:100%;line-height:0}
.shot-stage img{display:block;width:100%;height:auto;max-height:none;object-fit:fill}
.shot-overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.target-box{fill:#ffc4530b;stroke:#ffbd48;stroke-width:calc(4px * var(--capture-scale,1))}
.marker-disc{fill:#ffbd48;stroke:#182e25;stroke-width:3}
.marker-label{font:800 30px "Noto Sans TC","PingFang TC",sans-serif;fill:#10271d;text-anchor:middle}
.step-number{border:0;background:#e6ab3d;color:#142d26;display:flex;align-items:center;justify-content:center;align-self:start;border-radius:50%;width:32px;height:32px;padding:0;font:750 21px sans-serif}
.step.is-targeted h3{color:#926010}.shot-marker.is-targeted .target-box{fill:#ffbd4833;stroke-width:calc(7px * var(--capture-scale,1))}
#zoom-stage .shot-stage{width:min(88vw,calc(76dvh * var(--shot-aspect)))}#zoom-stage img{max-width:none;max-height:none}
@media(max-width:600px) and (min-height:501px){.body-grid{grid-template-columns:1fr;gap:10px}.shot-stage{width:min(100%,calc(20vh * var(--shot-aspect)))}.step-number{width:24px;height:24px;font-size:16px}.step{grid-template-columns:24px 1fr}.step p{font-size:14px}.step h3{font-size:15px}.lead{font-size:14px}.steps{gap:8px}h2{font-size:25px}}
@media(max-height:500px){.body-grid{grid-template-columns:1fr 1.1fr;gap:18px}.shot-stage{width:min(100%,calc(40vh * var(--shot-aspect)))}.step-number{width:23px;height:23px;font-size:16px}.step h3{font-size:14px}.step p{font-size:13px}.steps{gap:8px}}
@media print{.shot-stage{width:min(100%,calc(4.9in * var(--shot-aspect)))}.target-box{stroke-width:calc(4px * var(--capture-scale,1))}.step-number{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""
def steps_html(items):
    return '<div class="steps">'+''.join(f'<div class="step" data-step-number="{i}"><span class="step-number" aria-label="步驟 {i}">{i}</span><div><h3>{esc(a["title"])}</h3><p>{esc(a["body"])}</p></div></div>' for i,a in enumerate(items,1))+'</div>'

def image_html(s):
    raw=(ROOT/'assets'/s['image']).read_bytes()
    mime='image/jpeg' if s['image'].lower().endswith(('.jpg','.jpeg')) else 'image/png'
    uri='data:'+mime+';base64,'+base64.b64encode(raw).decode()
    capture=CAPTURES[s['id']]
    w,h=capture['width'],capture['height']
    # Markers use original image pixels; keep their CSS size at high-DPR captures.
    marker_scale=capture.get('pixel_ratio',1)
    marks=[]
    for m in s['markers']:
        b=m['target']
        leader=f'<line class="marker-leader" x1="{m["x"]}" y1="{m["y"]}" x2="{b["x"]}" y2="{m["y"]}" stroke="#ffbd48" stroke-width="{3*marker_scale}"/>' if m.get("leader") else ""
        marks.append(f'<g class="shot-marker" data-marker-step="{m["step"]}"><rect class="target-box" x="{b["x"]}" y="{b["y"]}" width="{b["width"]}" height="{b["height"]}" rx="{6*marker_scale}"/>{leader}<circle class="marker-disc" cx="{m["x"]}" cy="{m["y"]}" r="{25*marker_scale}" style="stroke-width:{3*marker_scale}px"/><text class="marker-label" style="font-size:{30*marker_scale}px" x="{m["x"]}" y="{m["y"]}" dy=".35em">{m["step"]}</text></g>')
    overlay=f'<svg class="shot-overlay" style="--capture-scale:{marker_scale}" viewBox="0 0 {w} {h}" aria-hidden="true">{"".join(marks)}</svg>'
    stage=f'<span class="shot-stage" style="--shot-aspect:{w/h:.8f}"><img src="{uri}" alt="{esc(s["caption"])}" width="{w}" height="{h}" decoding="async">{overlay}</span>'
    return f'<figure class="screen-figure"><button class="shot-button" type="button" aria-label="放大含步驟數字的截圖：{esc(s["caption"])}" data-zoom>{stage}</button><figcaption>{esc(s["caption"])}<span class="zoom-hint">點圖放大 · 數字與左側步驟一一對應</span></figcaption></figure>'
parts=[]
notes=['# Scout Permission 使用指南 — 講稿','',f'介面依據：{DATA["version"]}，來源提交 {DATA["basis_commit"]}。','本講稿與 HTML 簡報逐頁對應。截圖為 Scout 實際介面；教學／歷史樣本不代表使用者本次活動。','R4 保留待審，TRH 目前以 R1–R3 為主。','']
for i,s in enumerate(DATA['slides'],1):
    action = f' <a href="{esc(s["action_href"])}" target="_blank" rel="noopener noreferrer">{esc(s["action_label"])}</a>' if s.get("action_href") else ""
    head=f'<div class="header"><div class="eyebrow"><span class="wordmark">SCOUT</span><span>{esc(s["chapter"])}</span></div><h2 id="title-{i}">{esc(s["title"])}</h2><p class="lead">{esc(s.get("lead",""))}{action}</p></div>'
    kind=s['kind']
    if kind=='cover':
        c=f'<div class="contours decorative" aria-hidden="true"></div><div class="reveal"><div class="eyebrow"><span class="wordmark">SCOUT</span><span>FIELD GUIDE / 01</span></div><h1 id="title-{i}">{esc(s["title"])}</h1><h2>{esc(s["lead"])}</h2><p class="tagline">{esc(s["tagline"])}</p><p class="cover-meta">{len(DATA["slides"])} 頁 · 約 {round(sum(s["duration"] for s in DATA["slides"])/60)} 分鐘 · {esc(DATA["version"].replace("-", "."))} 介面版<br>方向鍵翻頁 · 目錄跳章 · 自動播放無旁白</p></div>'
    elif kind=='cards':
        rows=[]
        for a in s['cards']:
            tag='button' if 'go' in a else 'article'
            action=f' type="button" data-goto="{a["go"]}"' if 'go' in a else ''
            rows.append(f'<{tag} class="guide-card"{action}><h3>{esc(a["title"])}</h3><p>{esc(a["body"])}</p><span class="card-tag">{esc(a["tag"])}</span></{tag}>')
        c=head+'<div class="content card-grid reveal">'+''.join(rows)+'</div>'
    elif kind=='screen':c=head+'<div class="content body-grid reveal">'+steps_html(s['steps'])+image_html(s)+'</div>'
    elif kind=='example':c=head+'<div class="content body-grid reveal"><div class="example-box"><span class="example-label">教學句型 · 地名需替換</span>'+esc(s['example'])+'</div>'+steps_html(s['steps'])+'</div>'
    elif kind=='status':
        rows=''.join(f'<article class="status-row {esc(a["tone"])}"><h3>{esc(a["label"])}</h3><p>{esc(a["body"])}</p></article>' for a in s['rows'])
        c=head+'<div class="content status-grid reveal">'+rows+'</div>'
    else:c=head+'<div class="content reveal">'+steps_html(s['steps'])+'</div>'
    if s.get('takeaway'):c+=f'<p class="takeaway">{esc(s["takeaway"])}</p>'
    c+=f'<div class="slide-foot"><span>PERMISSION / 使用指南</span><span class="foot-detail">{esc(s["chapter"])}</span><span>{i:02} / {len(DATA["slides"]):02}</span></div>'
    parts.append(f'<section class="slide {esc(kind)}" id="slide-{i}" aria-labelledby="title-{i}" data-duration="{s["duration"]}" data-page-id="{esc(s["id"])}">{c}</section>')
    notes += [f'## {i:02}. {s["title"]}','',s['note'],'']
    if s.get('steps'):notes+=['操作順序：','']+[f'{j}. **{a["title"]}**：{a["body"]}' for j,a in enumerate(s['steps'],1)]+['']
    if s.get('image'):
        shot=CAPTURES[s['id']]
        notes += [f'截圖：assets/{s["image"]}。{s["caption"]}。',f'實際專案：{shot["project"]}；擷取時間：{shot["captured_at"]}。',f'來源畫面：{shot["url"]}','']
        notes += [f'步驟 {m["step"]} 對應 {m["locator"]}；圖上框線依 capture-sources.json 的 DOM 座標。' for m in s['markers']]+['']
    if s.get("action_href"):notes += [f'[開啟練習工作區]({s["action_href"]})', ""]
JS=r"""
class PresentationController {
 constructor(){
  this.slides=[...document.querySelectorAll('.slide')];this.current=0;this.timer=null;this.playing=false;this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  this.select=document.querySelector('#chapter');this.index=document.querySelector('#slide-index');this.prev=document.querySelector('#previous');this.next=document.querySelector('#next');this.play=document.querySelector('#play');this.progress=document.querySelector('#progress');
  this.observer=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting&&e.intersectionRatio>.6){const i=this.slides.indexOf(e.target);if(this.scrollTarget!=null&&i!==this.scrollTarget&&Date.now()<this.scrollDeadline)continue;this.scrollTarget=null;this.slides.forEach(s=>s.classList.remove('is-visible'));e.target.classList.add('is-visible');if(i!==this.current){this.current=i;this.update();if(this.playing)this.schedule();}}},{threshold:[.6]});
  this.slides.forEach(s=>this.observer.observe(s));this.prev.addEventListener('click',()=>this.go(this.current-1));this.next.addEventListener('click',()=>this.go(this.current+1));this.select.addEventListener('change',()=>this.go(Number(this.select.value)));
  document.querySelectorAll('[data-goto]').forEach(b=>b.addEventListener('click',()=>this.go(Number(b.dataset.goto)-1)));
  this.play.addEventListener('click',()=>this.togglePlay());document.querySelector('#fullscreen').addEventListener('click',()=>{if(document.fullscreenElement)document.exitFullscreen?.();else document.documentElement.requestFullscreen?.().catch(()=>{});});
  document.addEventListener('keydown',e=>{if(document.querySelector('dialog[open]')||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.altKey||e.ctrlKey||e.metaKey)return;if(e.code==='Space'&&e.target.closest('button,a'))return;
   if(['ArrowRight','ArrowDown','PageDown','Space'].includes(e.code)){e.preventDefault();this.go(this.current+1);}if(['ArrowLeft','ArrowUp','PageUp'].includes(e.code)){e.preventDefault();this.go(this.current-1);}if(e.code==='Home'){e.preventDefault();this.go(0);}if(e.code==='End'){e.preventDefault();this.go(this.slides.length-1);}});
  let wheelAt=0;document.addEventListener('wheel',e=>{if(e.ctrlKey||document.querySelector('dialog[open]')||e.target.closest('select'))return;if(Math.abs(e.deltaY)<12)return;e.preventDefault();if(Date.now()-wheelAt<600)return;wheelAt=Date.now();this.go(this.current+(e.deltaY>0?1:-1));},{passive:false});
  let touch=null;document.addEventListener('touchstart',e=>{if(e.touches.length===1)touch={x:e.touches[0].clientX,y:e.touches[0].clientY};},{passive:true});
  document.addEventListener('touchend',e=>{if(!touch||document.querySelector('dialog[open]'))return;const dx=e.changedTouches[0].clientX-touch.x,dy=e.changedTouches[0].clientY-touch.y;touch=null;if(Math.abs(dx)>60&&Math.abs(dx)>Math.abs(dy))this.go(this.current+(dx<0?1:-1));},{passive:true});
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&this.playing)this.togglePlay();});
  window.addEventListener('hashchange',()=>{const n=Number(location.hash.replace('#slide-',''));if(n>=1&&n<=this.slides.length)this.go(n-1,false);});
  window.addEventListener('resize',()=>{clearTimeout(this.resizeTimer);this.resizeTimer=setTimeout(()=>this.go(this.current,false),120);});
  const initial=Number(location.hash.replace('#slide-',''));this.go(initial>=1&&initial<=this.slides.length?initial-1:0,false);
 }
 go(i,smooth=true){const distance=Math.abs(i-this.current);this.current=Math.max(0,Math.min(this.slides.length-1,i));this.scrollTarget=this.current;this.scrollDeadline=Date.now()+1000;window.scrollTo({top:this.slides[this.current].offsetTop,behavior:smooth&&!this.reduced&&distance===1?'smooth':'instant'});this.slides.forEach((s,n)=>s.classList.toggle('is-visible',n===this.current));this.update();if(this.playing)this.schedule();}
 update(){this.select.value=String(this.current);this.index.textContent=(this.current+1)+' / '+this.slides.length;this.prev.disabled=this.current===0;this.next.disabled=this.current===this.slides.length-1;this.progress.style.width=((this.current+1)/this.slides.length*100)+'%';history.replaceState(null,'','#slide-'+(this.current+1));this.slides.forEach((s,n)=>n===this.current?s.setAttribute('aria-current','step'):s.removeAttribute('aria-current'));}
 togglePlay(){this.playing=!this.playing;this.play.textContent=this.playing?'暫停':'播放';this.play.setAttribute('aria-pressed',String(this.playing));this.play.setAttribute('aria-label',this.playing?'暫停自動播放':'自動播放簡報，無旁白');if(this.playing){if(this.current===this.slides.length-1)this.go(0);this.schedule();}else clearTimeout(this.timer);}
 schedule(){clearTimeout(this.timer);this.timer=setTimeout(()=>{if(this.current===this.slides.length-1){this.togglePlay();return;}this.go(this.current+1);},Number(this.slides[this.current].dataset.duration)*1000);}
}
window.presentation=new PresentationController();
const dialog=document.querySelector('#zoom-dialog'),zoomStage=document.querySelector('#zoom-stage'),zoomCaption=document.querySelector('#zoom-caption');
document.querySelectorAll('[data-zoom]').forEach(button=>button.addEventListener('click',()=>{if(presentation.playing)presentation.togglePlay();zoomStage.replaceChildren(button.querySelector('.shot-stage').cloneNode(true));zoomCaption.textContent=button.querySelector('img').alt;dialog.showModal();}));
document.querySelectorAll('.step').forEach(step=>{step.addEventListener('pointerenter',()=>{const slide=step.closest('.slide');slide.querySelectorAll('.is-targeted').forEach(e=>e.classList.remove('is-targeted'));step.classList.add('is-targeted');slide.querySelector('[data-marker-step="'+step.dataset.stepNumber+'"]')?.classList.add('is-targeted');});step.addEventListener('pointerleave',()=>step.closest('.slide').querySelectorAll('.is-targeted').forEach(e=>e.classList.remove('is-targeted')));});
document.querySelector('#close-zoom').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});

"""
options=''.join(f'<option value="{i-1}">{i:02} · {esc(s["title"])}</option>' for i,s in enumerate(DATA['slides'],1))
doc=f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><meta name="description" content="Scout Permission 操作教學：Golden、人工行程與 Planned GPX、R1–R3、Recorded 復盤。"><title>Scout Permission 使用指南</title><style>{CSS}</style></head>
<body><main>{''.join(parts)}</main><nav class="nav" aria-label="簡報導覽"><button id="previous" aria-label="上一頁">←</button><button id="next" aria-label="下一頁">→</button><span class="index" id="slide-index" aria-live="polite"></span><select id="chapter" aria-label="選擇教學頁面">{options}</select><button class="play" id="play" aria-pressed="false" aria-label="自動播放簡報，無旁白">播放</button><span class="spacer"></span><span class="keyboard-hint">← → 翻頁 · 點圖放大</span><a class="secondary" href="permission-guide.pdf" download>PDF</a><a class="secondary" href="presenter-notes.md" download>講稿</a><button class="full" id="fullscreen" aria-label="切換全螢幕">全螢幕</button></nav><div class="progress" id="progress" role="presentation"></div><dialog id="zoom-dialog" aria-label="放大介面截圖"><div class="dialog-head"><span id="zoom-caption"></span><button id="close-zoom">關閉</button></div><div id="zoom-stage"></div></dialog><script>{JS}</script></body></html>"""
(ROOT/'index.html').write_text(doc)
(ROOT/'presenter-notes.md').write_text('\n'.join(notes).rstrip()+'\n')
manifest={'title':DATA['title'],'version':DATA['version'],'basis_commit':DATA['basis_commit'],'slide_count':len(DATA['slides']),'autoplay_seconds':sum(s['duration'] for s in DATA['slides']),'screenshots':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted({ROOT/'assets'/s['image'] for s in DATA['slides']})},'files':{n:{'bytes':(ROOT/n).stat().st_size,'sha256':hashlib.sha256((ROOT/n).read_bytes()).hexdigest()} for n in ['index.html','presenter-notes.md','slides.json','capture-sources.json','build.py','verify-browser.js']},'boundary':'candidate_only=true; runtime_safety_truth=false; R4 deferred; no human review submitted'}
(ROOT/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'BUILT','slides':len(DATA['slides']),'seconds':manifest['autoplay_seconds'],'html_bytes':len(doc.encode())}))
