"""
Pashu Aadhaar - demo web app.

Run:   python app.py      then open http://localhost:5000
On a phone on the same Wi-Fi: http://<your-laptop-ip>:5000  (camera upload works)
"""

import base64
import os
import shutil
import socket

import cv2
from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for

import pashu_core as pc

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(HERE, "static"))
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
DB = os.environ.get("PASHU_DB", os.path.join(HERE, "db"))
DEMO = os.path.join(HERE, "demo_db")
# First start (e.g. a fresh cloud deploy): load the 20 demo cows.
if os.path.isdir(DEMO) and (not os.path.isdir(DB) or not os.listdir(DB)):
    shutil.copytree(DEMO, DB, dirs_exist_ok=True)
reg = pc.Registry(DB)

FIELDS = ("owner", "phone", "village", "species", "breed", "tag", "insurance")

PAGE = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pashu Aadhaar</title>
<link rel="stylesheet" href="{{ url_for('static', filename='cropper.min.css') }}">
<style>
 :root{--g:#1f6f43;--g2:#e7f3ec;--o:#e8772e;--r:#c0392b;--r2:#fdecea;--y2:#fff8e6;--bg:#f6f4ee;--card:#fff;--ink:#222;--mut:#666}
 *{box-sizing:border-box} body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
 header{background:var(--g);color:#fff;padding:16px 20px}
 header h1{margin:0;font-size:24px} header p{margin:4px 0 0;opacity:.85;font-size:14px}
 nav{display:flex;gap:6px;padding:10px 16px;background:#fff;border-bottom:1px solid #ddd;flex-wrap:wrap;position:sticky;top:0;z-index:5}
 nav a{padding:8px 14px;border-radius:20px;text-decoration:none;color:var(--g);font-weight:600}
 nav a.on{background:var(--g);color:#fff}
 main{max-width:860px;margin:18px auto;padding:0 16px}
 .card{background:var(--card);border-radius:12px;padding:20px;box-shadow:0 1px 3px #0002;margin-bottom:16px}
 h2{margin-top:0}
 label{display:block;font-weight:600;margin:12px 0 4px} .hi{color:var(--mut);font-weight:400}
 input[type=text],input[type=tel],select{width:100%;padding:11px;border:1px solid #ccc;border-radius:8px;font-size:16px}
 .row{display:grid;grid-template-columns:1fr 1fr;gap:0 12px} @media(max-width:560px){.row{grid-template-columns:1fr}}
 button,.btn{display:inline-block;margin-top:16px;background:var(--o);color:#fff;border:0;padding:13px 22px;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;text-decoration:none}
 button.sec,.btn.sec{background:#fff;color:var(--g);border:2px solid var(--g)}
 button.del{background:#fff;color:var(--r);border:1px solid var(--r);padding:6px 12px;font-size:13px;margin:0}
 button:disabled{opacity:.5;cursor:not-allowed}
 .ok{border-left:6px solid var(--g);background:var(--g2)} .no{border-left:6px solid var(--r);background:var(--r2)} .warn{border-left:6px solid var(--o);background:var(--y2)}
 .big{font-size:22px;font-weight:800;margin:0 0 8px}
 table{width:100%;border-collapse:collapse;font-size:14px} td,th{padding:8px;border-bottom:1px solid #eee;text-align:left;vertical-align:middle}
 .tablewrap{overflow-x:auto}
 img.vis{width:100%;border-radius:8px;margin-top:12px;background:#fff} img.th{width:56px;height:56px;object-fit:cover;border-radius:6px;display:block}
 .bar{height:10px;background:#eee;border-radius:5px;overflow:hidden;min-width:60px} .bar i{display:block;height:100%;background:var(--g)}
 .tip{font-size:13px;color:var(--mut);background:var(--y2);padding:10px;border-radius:8px;margin-top:12px}
 .shots{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
 .shot{position:relative;width:96px;height:96px} .shot img{width:100%;height:100%;object-fit:cover;border-radius:8px;border:2px solid var(--g)}
 .shot b{position:absolute;top:-8px;right:-8px;background:var(--r);color:#fff;border-radius:50%;width:24px;height:24px;text-align:center;line-height:24px;cursor:pointer;font-size:14px}
 .add{width:96px;height:96px;border:2px dashed var(--g);border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--g);font-weight:700;cursor:pointer;font-size:13px;text-align:center}
 .add span{font-size:30px;line-height:1}
 .pick{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;border:2px dashed var(--g);border-radius:12px;padding:30px;color:var(--g);font-weight:700;cursor:pointer;text-align:center}
 .pick span{font-size:44px}
 .photos{display:flex;gap:10px;flex-wrap:wrap} .photos img{width:150px;height:150px;object-fit:cover;border-radius:8px}
 .idbadge{font-family:ui-monospace,Consolas,monospace;font-size:26px;font-weight:800;letter-spacing:1px;color:var(--g)}
 .stats{display:flex;gap:12px;flex-wrap:wrap} .stat{flex:1;min-width:120px;background:var(--g2);border-radius:10px;padding:12px;text-align:center}
 .stat b{display:block;font-size:26px;color:var(--g)}
 /* crop dialog */
 #cropdlg{position:fixed;inset:0;background:#000d;display:none;flex-direction:column;z-index:50}
 #cropdlg.on{display:flex}
 #cropdlg .hd{color:#fff;padding:12px 16px;font-weight:600}
 #cropdlg .bd{flex:1;min-height:0} #cropdlg .bd img{display:block;max-width:100%}
 #cropdlg .ft{display:flex;gap:10px;padding:12px 16px;justify-content:flex-end;flex-wrap:wrap}
 #cropdlg .ft button{margin:0}
 /* busy overlay */
 #busy{position:fixed;inset:0;background:#fffc;display:none;align-items:center;justify-content:center;flex-direction:column;z-index:60;font-weight:700;color:var(--g)}
 #busy.on{display:flex}
 .spin{width:54px;height:54px;border:6px solid var(--g2);border-top-color:var(--g);border-radius:50%;animation:s 1s linear infinite;margin-bottom:14px}
 @keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<header><h1>🐄 Pashu Aadhaar</h1><p>Nose-print ID for cattle · पशु की नाक से पहचान</p></header>
<nav>
 <a href="/" class="{{'on' if tab=='identify'}}">🔍 Identify · पहचानें</a>
 <a href="/register" class="{{'on' if tab=='register'}}">➕ Register · पंजीकरण</a>
 <a href="/cows" class="{{'on' if tab in ('cows','cow')}}">📋 Registry ({{n}})</a>
</nav><main>

{% if err %}<div class="card no"><p class="big">⚠️ {{err_title or 'Please retake the photo'}}</p>{{err}}</div>{% endif %}

{# ============================== IDENTIFY ============================== #}
{% if tab=='identify' %}
 {% if res %}
  {% if res.match %}{% set m = res.match %}
  <div class="card ok"><p class="big">✅ Match found · पहचान हो गई</p>
   <p class="idbadge">{{m.id}}</p>
   <table>
    <tr><td>Owner · मालिक</td><td><b>{{m.owner}}</b> {% if m.phone %}· {{m.phone}}{% endif %}</td></tr>
    <tr><td>Village · गाँव</td><td>{{m.village}}</td></tr>
    <tr><td>Animal · पशु</td><td>{{m.species}} {% if m.breed %}· {{m.breed}}{% endif %}</td></tr>
    {% if m.tag %}<tr><td>Ear tag · टैग</td><td>{{m.tag}}</td></tr>{% endif %}
    <tr><td>Insurance · बीमा</td><td>{{m.insurance}}</td></tr>
    <tr><td>Registered</td><td>{{m.registered_at}}</td></tr>
    <tr><td>Confidence</td><td><b>{{m.confidence}}%</b> · {{m.inliers}} matching ridge points</td></tr>
   </table>
   <img class="vis" src="data:image/jpeg;base64,{{visual}}" alt="matched ridge points">
   <div class="tip">Left: new photo. Right: registered photo. Green lines join the same nose-ridge points found in both.</div>
   <a class="btn sec" href="/cow/{{m.id}}">View full record</a>
  </div>
  {% else %}
  <div class="card no"><p class="big">❌ Not registered · पंजीकृत नहीं</p>
   This nose print doesn't match any of the {{n}} registered animals.
   <b>If this is an insurance claim, flag it for verification.</b>
   <br><a class="btn sec" href="/register">Register this animal</a>
  </div>
  {% endif %}
  {% if res.candidates %}
  <div class="card"><h3 style="margin-top:0">Closest animals in registry</h3><div class="tablewrap"><table>
   <tr><th>Pashu ID</th><th>Owner</th><th>Ridge points</th><th style="width:30%">Score</th></tr>
   {% for c in res.candidates %}<tr><td><a href="/cow/{{c.id}}">{{c.id}}</a></td><td>{{c.owner}}</td><td>{{c.inliers}}</td>
   <td><div class="bar"><i style="width:{{c.confidence}}%"></i></div></td></tr>{% endfor %}</table></div>
   <p class="hi">Match needs {{threshold}}+ ridge points. New photo had {{res.query_keypoints}} ridge features.</p></div>
  {% endif %}
 {% endif %}

 <div class="card"><h2>{{ 'Check another animal' if res else 'Identify an animal' }}</h2>
 <form method="post" enctype="multipart/form-data" action="/" id="idform" data-single>
  <input type="file" name="photo" accept="image/*" hidden class="real">
  <label class="pick" data-add><span>📷</span>Take / choose nose photo<br><small class="hi">नाक की फोटो लें</small></label>
  <div class="tip">Fill the frame with the nose (muzzle), daylight, hold steady. You can adjust the crop next.</div>
 </form></div>
 {% if n == 0 %}<div class="card warn">The registry is empty. <a href="/register">Register a few animals first</a>.</div>{% endif %}

{# ============================== REGISTER ============================== #}
{% elif tab=='register' %}
 {% if done %}
 <div class="card ok"><p class="big">✅ Registered! · पंजीकरण सफल</p>
  <p>Pashu Aadhaar ID</p><p class="idbadge">{{done.id}}</p>
  <p>{{done.owner}} · {{done.village}} · {{done.photos}} nose photo(s) saved.</p>
  {% if rejected %}<div class="tip">Skipped: {{ rejected|join('; ') }}</div>{% endif %}
  <a class="btn sec" href="/cow/{{done.id}}">View record</a> <a class="btn" href="/register">Register another</a>
 </div>
 {% elif dup %}
 <div class="card no"><p class="big">🚫 Already registered · पहले से पंजीकृत</p>
  This animal matches <a href="/cow/{{dup.cid}}"><b>{{dup.cid}}</b></a>
  (owner <b>{{dup.info.owner}}</b>{% if dup.info.village %}, {{dup.info.village}}{% endif %}),
  with {{dup.inliers}} matching ridge points.<br><b>Duplicate registration blocked.</b>
 </div>
 {% endif %}
 {% if not done %}
 <div class="card"><h2>Register a new animal</h2>
 <form method="post" enctype="multipart/form-data" action="/register" id="regform">
  <label>Nose photos <span class="hi">· नाक की 2–3 फोटो</span></label>
  <input type="file" name="photos" accept="image/*" multiple hidden class="real">
  <div class="shots"><label class="add" data-add><span>+</span>Add photo</label></div>
  <div class="tip">Take 2–3 photos a few seconds apart, from slightly different angles.</div>
  <div class="row">
   <div><label>Owner name <span class="hi">· मालिक का नाम</span></label><input type="text" name="owner" required value="{{form.owner}}"></div>
   <div><label>Mobile <span class="hi">· मोबाइल</span></label><input type="tel" name="phone" value="{{form.phone}}"></div>
   <div><label>Village / District <span class="hi">· गाँव / ज़िला</span></label><input type="text" name="village" value="{{form.village}}"></div>
   <div><label>Animal <span class="hi">· पशु</span></label><select name="species">
     {% for o in ['Cow · गाय','Buffalo · भैंस','Bull · बैल'] %}<option {{'selected' if form.species==o}}>{{o}}</option>{% endfor %}</select></div>
   <div><label>Breed <span class="hi">· नस्ल</span></label><input type="text" name="breed" placeholder="Gir, Sahiwal, Murrah, HF cross..." value="{{form.breed}}"></div>
   <div><label>Ear tag no. <span class="hi">· टैग नंबर (optional)</span></label><input type="text" name="tag" value="{{form.tag}}"></div>
  </div>
  <label>Insurance status <span class="hi">· बीमा</span></label>
  <select name="insurance">{% for o in ['Not insured','Insured','Claim pending'] %}<option {{'selected' if form.insurance==o}}>{{o}}</option>{% endfor %}</select>
  <button type="submit" id="regbtn" disabled>Register · पंजीकरण करें</button>
 </form></div>
 {% endif %}

{# ============================== REGISTRY ============================== #}
{% elif tab=='cows' %}
<div class="card"><h2>Registered animals</h2>
 <div class="stats"><div class="stat"><b>{{n}}</b>animals</div><div class="stat"><b>{{photos}}</b>nose photos</div>
 <div class="stat"><b>{{insured}}</b>insured</div></div>
{% if cows %}<div class="tablewrap"><table style="margin-top:14px"><tr><th></th><th>Pashu ID</th><th>Owner</th><th>Village</th><th>Animal</th><th>Insurance</th></tr>
{% for c in cows %}<tr onclick="location='/cow/{{c.id}}'" style="cursor:pointer"><td><img class="th" src="/photo/{{c.id}}/0" alt=""></td>
<td><a href="/cow/{{c.id}}"><b>{{c.id}}</b></a></td><td>{{c.owner}}</td><td>{{c.village}}</td>
<td>{{c.species}} {{c.breed}}</td><td>{{c.insurance}}</td></tr>{% endfor %}</table></div>
{% else %}<p>No animals yet. <a href="/register">Register one</a>.</p>{% endif %}</div>

{% elif tab=='cow' %}
<div class="card"><p class="hi" style="margin:0">Pashu Aadhaar ID</p><p class="idbadge" style="margin-top:4px">{{cow.id}}</p>
 <table>
  <tr><td>Owner · मालिक</td><td><b>{{cow.owner}}</b></td></tr>
  {% if cow.phone %}<tr><td>Mobile</td><td>{{cow.phone}}</td></tr>{% endif %}
  <tr><td>Village · गाँव</td><td>{{cow.village}}</td></tr>
  <tr><td>Animal · पशु</td><td>{{cow.species}} {% if cow.breed %}· {{cow.breed}}{% endif %}</td></tr>
  {% if cow.tag %}<tr><td>Ear tag</td><td>{{cow.tag}}</td></tr>{% endif %}
  <tr><td>Insurance · बीमा</td><td>{{cow.insurance}}</td></tr>
  <tr><td>Registered</td><td>{{cow.registered_at}}</td></tr>
 </table>
 <h3>Nose prints</h3>
 <div class="photos">{% for i in range(cow.photos) %}<img src="/photo/{{cow.id}}/{{i}}" alt="nose print {{i+1}}">{% endfor %}</div>
 <form method="post" action="/cow/{{cow.id}}/delete" onsubmit="return confirm('Delete {{cow.id}} from the registry?')" style="margin-top:20px">
  <button class="del">Delete record</button></form>
</div>
{% endif %}
</main>

<div id="cropdlg"><div class="hd">Drag the box over the nose · बॉक्स को नाक पर रखें</div>
 <div class="bd"><img id="cropimg" alt=""></div>
 <div class="ft"><button type="button" class="sec" id="cropcancel">Cancel</button>
 <button type="button" class="sec" id="croprot">↻ Rotate</button>
 <button type="button" id="cropok">Use photo ✓</button></div></div>
<div id="busy"><div class="spin"></div><span id="busytxt">Reading nose print…</span></div>

<script src="{{ url_for('static', filename='cropper.min.js') }}"></script>
<script>
(function(){
  const OUT = 640;                       // cropped photo size sent to server
  const dlg = document.getElementById('cropdlg'), img = document.getElementById('cropimg');
  const busy = (t) => { document.getElementById('busytxt').textContent = t; document.getElementById('busy').classList.add('on'); };
  let cropper = null, queue = [], onDone = null;

  // Fallback when Cropper failed to load: just downscale the photo.
  function downscale(file) {
    return new Promise(res => {
      const im = new Image();
      im.onload = () => {
        const s = Math.min(1, 1600 / Math.max(im.width, im.height));
        const c = document.createElement('canvas'); c.width = im.width * s; c.height = im.height * s;
        c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
        c.toBlob(b => res(b), 'image/jpeg', 0.92);
      };
      im.onerror = () => res(file);
      im.src = URL.createObjectURL(file);
    });
  }

  function openNext() {
    if (!queue.length) return;
    const file = queue[0];
    if (typeof Cropper === 'undefined') { queue.shift(); downscale(file).then(b => { onDone(b); openNext(); }); return; }
    img.src = URL.createObjectURL(file);
    dlg.classList.add('on');
    if (cropper) cropper.destroy();
    cropper = new Cropper(img, {aspectRatio: 1, viewMode: 1, autoCropArea: 0.7, background: false,
                                movable: true, zoomable: true, rotatable: true, checkOrientation: true});
  }
  function close() { dlg.classList.remove('on'); if (cropper) { cropper.destroy(); cropper = null; } }
  document.getElementById('cropcancel').onclick = () => { queue.shift(); close(); openNext(); };
  document.getElementById('croprot').onclick = () => cropper && cropper.rotate(90);
  document.getElementById('cropok').onclick = () => {
    const canvas = cropper.getCroppedCanvas({width: OUT, height: OUT, imageSmoothingQuality: 'high', fillColor: '#000'});
    canvas.toBlob(b => { queue.shift(); close(); onDone(b); openNext(); }, 'image/jpeg', 0.92);
  };

  function setFiles(input, blobs) {
    const dt = new DataTransfer();
    blobs.forEach((b, i) => dt.items.add(new File([b], 'nose' + i + '.jpg', {type: 'image/jpeg'})));
    input.files = dt.files;
  }

  // ---- identify: one photo, crop, auto-submit
  const idf = document.getElementById('idform');
  if (idf) {
    const real = idf.querySelector('.real'), picker = document.createElement('input');
    picker.type = 'file'; picker.accept = 'image/*';
    idf.querySelector('[data-add]').onclick = (e) => { e.preventDefault(); picker.value = ''; picker.click(); };
    picker.onchange = () => {
      if (!picker.files.length) return;
      queue = [picker.files[0]];
      onDone = (b) => { setFiles(real, [b]); busy('Searching registry… · खोज रहे हैं'); idf.submit(); };
      openNext();
    };
  }

  // ---- register: collect up to 5 cropped photos
  const rf = document.getElementById('regform');
  if (rf) {
    const real = rf.querySelector('.real'), shots = rf.querySelector('.shots'), add = rf.querySelector('[data-add]');
    const btn = document.getElementById('regbtn'), picker = document.createElement('input');
    picker.type = 'file'; picker.accept = 'image/*'; picker.multiple = true;
    let blobs = [];
    function draw() {
      shots.querySelectorAll('.shot').forEach(e => e.remove());
      blobs.forEach((b, i) => {
        const d = document.createElement('div'); d.className = 'shot';
        d.innerHTML = '<img alt=""><b title="remove">×</b>';
        d.querySelector('img').src = URL.createObjectURL(b);
        d.querySelector('b').onclick = () => { blobs.splice(i, 1); draw(); };
        shots.insertBefore(d, add);
      });
      add.style.display = blobs.length >= 5 ? 'none' : '';
      btn.disabled = blobs.length === 0;
      btn.textContent = blobs.length < 2 && blobs.length > 0 ? 'Register (2–3 photos recommended)' : 'Register · पंजीकरण करें';
      setFiles(real, blobs);
    }
    add.onclick = (e) => { e.preventDefault(); picker.value = ''; picker.click(); };
    picker.onchange = () => {
      queue = Array.from(picker.files).slice(0, 5 - blobs.length);
      onDone = (b) => { blobs.push(b); draw(); };
      openNext();
    };
    rf.addEventListener('submit', () => busy('Registering… · पंजीकरण हो रहा है'));
    draw();
  }
})();
</script>
</body></html>
"""


def render(tab, **kw):
    kw.setdefault("form", {})
    return render_template_string(PAGE, tab=tab, n=len(reg), threshold=pc.DEFAULT_THRESHOLD, **kw)


def read_upload(f):
    if not f or not f.filename:
        return None
    try:
        return pc.load_image(f.read())
    except ValueError:
        return None


@app.route("/", methods=["GET", "POST"])
def identify():
    if request.method == "GET":
        return render("identify")
    img = read_upload(request.files.get("photo"))
    if img is None:
        return render("identify", err="That file isn't a photo we can read. Please try again.")
    if len(reg) == 0:
        return render("identify", err="The registry is empty. Register some animals first.",
                      err_title="Nothing to search")
    try:
        res = reg.identify(img)
    except ValueError as e:
        return render("identify", err=f"The photo is {e}.")
    visual = None
    if res["visual"] is not None:
        _, buf = cv2.imencode(".jpg", res["visual"], [cv2.IMWRITE_JPEG_QUALITY, 85])
        visual = base64.b64encode(buf).decode()
    return render("identify", res=res, visual=visual)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render("register")
    form = {k: request.form.get(k, "").strip()[:120] for k in FIELDS}
    imgs = [i for i in (read_upload(f) for f in request.files.getlist("photos")) if i is not None]
    if not imgs:
        return render("register", form=form, err="Add at least one nose photo.")
    if not form["owner"]:
        return render("register", form=form, err="Owner name is required.", err_title="Missing details")
    try:
        cid, rejected = reg.enroll(imgs, form)
    except pc.DuplicateError as d:
        return render("register", form=form, dup=d)
    except ValueError as e:
        return render("register", form=form, err=str(e))
    return render("register", done=dict(id=cid, **reg.info(cid)), rejected=rejected)


@app.route("/cows")
def cows():
    cs = reg.cows()
    return render("cows", cows=cs, photos=sum(c.get("photos", 0) for c in cs),
                  insured=sum(1 for c in cs if c.get("insurance") == "Insured"))


@app.route("/cow/<cid>")
def cow(cid):
    if not reg.has(cid):
        abort(404)
    return render("cow", cow=dict(id=cid, **reg.info(cid)))


@app.route("/cow/<cid>/delete", methods=["POST"])
def delete(cid):
    reg.delete(cid)
    return redirect(url_for("cows"))


@app.route("/photo/<cid>/<int:i>")
@app.route("/photo/<cid>")
def photo(cid, i=0):
    if not reg.has(cid):
        abort(404)
    p = reg.photo_path(cid, i)
    if not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="image/jpeg")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


if __name__ == "__main__":
    ip = lan_ip()
    print("\n  Pashu Aadhaar is running")
    print("  On this laptop:  http://localhost:5000")
    if ip:
        print(f"  On your phone:   http://{ip}:5000   (same Wi-Fi)")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
