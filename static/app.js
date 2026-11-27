(function () {
  'use strict';
  const OUT = 640;
  const MAX_SHOTS = 5;
  const MAX_INPUT_BYTES = 20 * 1024 * 1024;
  let L = {};
  try { L = JSON.parse(document.body.dataset.i18n || '{}'); } catch (e) { L = {}; }
  const tr = (k, fb) => L[k] || fb;

  const dlg = document.getElementById('cropdlg');
  const img = document.getElementById('cropimg');
  const busyBox = document.getElementById('busy');
  const busy = (t) => {
    document.getElementById('busytxt').textContent = t;
    busyBox.classList.add('on');
  };
  window.addEventListener('pageshow', () => busyBox.classList.remove('on'));

  let cropper = null, queue = [], onDone = null, lastUrl = null, lastFocus = null;

  function objUrl(file) {
    if (lastUrl) URL.revokeObjectURL(lastUrl);
    lastUrl = URL.createObjectURL(file);
    return lastUrl;
  }

  function acceptable(file) {
    return /^image\/(jpeg|png|webp)$/.test(file.type) && file.size <= MAX_INPUT_BYTES;
  }

  function downscale(file) {
    return new Promise((res) => {
      const im = new Image();
      im.onload = () => {
        const s = Math.min(1, 1600 / Math.max(im.width, im.height));
        const c = document.createElement('canvas');
        c.width = Math.round(im.width * s); c.height = Math.round(im.height * s);
        c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
        c.toBlob((b) => res(b), 'image/jpeg', 0.92);
      };
      im.onerror = () => res(null);
      im.src = objUrl(file);
    });
  }

  function openNext() {
    while (queue.length && !acceptable(queue[0])) {
      queue.shift();
      alert(tr('f_avatar_type', 'Please choose a JPG, PNG or WebP image.'));
    }
    if (!queue.length) return;
    const file = queue[0];
    if (typeof Cropper === 'undefined') {
      queue.shift();
      downscale(file).then((b) => { if (b) onDone(b); openNext(); });
      return;
    }
    lastFocus = document.activeElement;
    img.src = objUrl(file);
    dlg.classList.add('on');
    if (cropper) cropper.destroy();
    cropper = new Cropper(img, {
      aspectRatio: 1, viewMode: 1, autoCropArea: 0.85, background: false,
      movable: true, zoomable: true, rotatable: true, checkOrientation: true
    });
    document.getElementById('cropok').focus();
  }

  function close() {
    dlg.classList.remove('on');
    if (cropper) { cropper.destroy(); cropper = null; }
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (dlg) {
    document.getElementById('cropcancel').addEventListener('click', () => { queue.shift(); close(); openNext(); });
    document.getElementById('croprot').addEventListener('click', () => cropper && cropper.rotate(90));
    document.getElementById('cropok').addEventListener('click', () => {
      if (!cropper) return;
      const area = cropper.getData(true);
    const side = Math.max(1, Math.min(OUT, Math.round(Math.min(area.width, area.height))));
    const canvas = cropper.getCroppedCanvas({ width: side, height: side, imageSmoothingQuality: 'high', fillColor: '#000' });
      if (!canvas) return;
      canvas.toBlob((b) => { queue.shift(); close(); if (b) onDone(b); openNext(); }, 'image/jpeg', 0.92);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dlg.classList.contains('on')) document.getElementById('cropcancel').click();
    });
  }

  function setFiles(input, blobs) {
    const dt = new DataTransfer();
    blobs.forEach((b, i) => dt.items.add(new File([b], 'nose' + i + '.jpg', { type: 'image/jpeg' })));
    input.files = dt.files;
  }

  function imagePicker(multiple) {
    const p = document.createElement('input');
    p.type = 'file';
    p.accept = 'image/jpeg,image/png,image/webp';
    p.multiple = multiple;
    return p;
  }

  const idf = document.getElementById('idform');
  if (idf) {
    const real = idf.querySelector('.real'), picker = imagePicker(false);
    let sent = false;
    idf.querySelector('[data-add]').addEventListener('click', (e) => { e.preventDefault(); picker.value = ''; picker.click(); });
    picker.addEventListener('change', () => {
      if (!picker.files.length) return;
      queue = [picker.files[0]];
      onDone = (b) => {
        if (sent) return;
        sent = true;
        setFiles(real, [b]);
        busy(tr('searching', 'Searching…'));
        idf.submit();
      };
      openNext();
    });
    window.addEventListener('pageshow', () => { sent = false; });
  }

  const rf = document.getElementById('regform');
  if (rf) {
    const real = rf.querySelector('.real'), shots = rf.querySelector('.shots'), add = rf.querySelector('[data-add]');
    const btn = document.getElementById('regbtn'), picker = imagePicker(true);
    const blobs = [];
    let sending = false;
    function draw() {
      shots.querySelectorAll('.shot').forEach((e) => {
        const im = e.querySelector('img');
        if (im) URL.revokeObjectURL(im.src);
        e.remove();
      });
      blobs.forEach((b, i) => {
        const d = document.createElement('div');
        d.className = 'shot';
        const im = document.createElement('img');
        im.alt = '';
        im.src = URL.createObjectURL(b);
        const x = document.createElement('button');
        x.type = 'button';
        x.textContent = '×';
        x.setAttribute('aria-label', tr('remove', 'Remove') + ' ' + (i + 1));
        x.addEventListener('click', () => { blobs.splice(i, 1); draw(); add.focus(); });
        d.append(im, x);
        shots.insertBefore(d, add);
      });
      add.hidden = blobs.length >= MAX_SHOTS;
      btn.disabled = blobs.length === 0;
      btn.textContent = blobs.length === 1 ? tr('register_btn_few', 'Register') : tr('register_btn', 'Register');
      setFiles(real, blobs);
    }
    add.addEventListener('click', (e) => { e.preventDefault(); picker.value = ''; picker.click(); });
    picker.addEventListener('change', () => {
      queue = Array.from(picker.files).slice(0, MAX_SHOTS - blobs.length);
      onDone = (b) => { if (blobs.length < MAX_SHOTS) blobs.push(b); draw(); };
      openNext();
    });
    rf.addEventListener('submit', (e) => {
      if (sending || !blobs.length) { e.preventDefault(); return; }
      sending = true;
      btn.disabled = true;
      busy(tr('registering', 'Registering…'));
    });
    window.addEventListener('pageshow', () => { sending = false; btn.disabled = blobs.length === 0; });
    draw();
  }

  document.querySelectorAll('[data-copy]').forEach((b) => {
    const src = document.getElementById(b.dataset.copy);
    if (!src || !navigator.clipboard) { b.hidden = true; return; }
    const label = b.textContent;
    b.addEventListener('click', () => {
      navigator.clipboard.writeText(src.innerText.trim()).then(() => {
        b.textContent = tr('codes_copied', 'Copied');
        setTimeout(() => { b.textContent = label; }, 1500);
      });
    });
  });

  document.querySelectorAll('[data-download]').forEach((b) => {
    const src = document.getElementById(b.dataset.download);
    if (!src) { b.hidden = true; return; }
    b.addEventListener('click', () => {
      const text = Array.from(src.querySelectorAll('code')).map((c) => c.textContent).join(String.fromCharCode(13, 10)) + String.fromCharCode(13, 10);
      const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = b.dataset.filename || 'recovery-codes.txt';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  });

  document.querySelectorAll('form[data-confirm]').forEach((f) => {
    f.addEventListener('submit', (e) => { if (!window.confirm(f.dataset.confirm)) e.preventDefault(); });
  });

  document.querySelectorAll('tr[data-href]').forEach((tr_) => {
    tr_.addEventListener('click', (e) => {
      if (e.target.closest('a,button,form,input')) return;
      if (window.getSelection && String(window.getSelection())) return;
      const href = tr_.dataset.href;
      if (href && href.charAt(0) === '/' && href.charAt(1) !== '/') window.location.assign(href);
    });
  });

  document.querySelectorAll('input[type=password]').forEach((input) => {
    if (!input.id || input.hidden || input.closest('.pw')) return;
    const wrap = document.createElement('div');
    wrap.className = 'pw';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'link';
    b.dataset.reveal = input.id;
    b.textContent = tr('show', 'Show');
    wrap.appendChild(b);
  });

  document.querySelectorAll('[data-reveal]').forEach((b) => {
    const input = document.getElementById(b.dataset.reveal);
    if (!input) return;
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      b.textContent = show ? tr('hide', 'Hide') : tr('show', 'Show');
      b.setAttribute('aria-pressed', String(show));
    });
  });

  document.querySelectorAll('input[data-preview]').forEach((input) => {
    const prev = document.getElementById(input.dataset.preview);
    input.addEventListener('change', () => {
      const f = input.files[0];
      if (!f || !prev) return;
      if (!/^image\/(jpeg|png|webp)$/.test(f.type) || f.size > 10 * 1024 * 1024) {
        alert(tr('f_avatar_type', 'Please choose a JPG, PNG or WebP image under 10 MB.'));
        input.value = '';
        prev.hidden = true;
        return;
      }
      if (prev.src) URL.revokeObjectURL(prev.src);
      prev.src = URL.createObjectURL(f);
      prev.hidden = false;
    });
  });

  document.querySelectorAll('input[data-strength]').forEach((input) => {
    const box = document.getElementById(input.dataset.strength);
    if (!box) return;
    const bar = box.querySelector('i'), label = box.querySelector('span');
    const names = tr('pw_levels', 'Too short|Weak|Fair|Good|Strong').split('|');
    const colors = ['#a3362a', '#a3362a', '#d08a1c', '#5f8f3a', '#1f4d36'];
    const hint = tr('pw_hint', '');
    input.addEventListener('input', () => {
      const v = input.value;
      if (!v) {
        bar.style.setProperty('--w', '0%');
        label.textContent = hint;
        return;
      }
      const ok = v.length >= 10 && /[A-Za-z]/.test(v) && /[0-9]/.test(v);
      let lvl = 0;
      if (v.length >= 10) lvl = 1;
      if (ok) {
        lvl = 2;
        if (v.length >= 14 || (/[a-z]/.test(v) && /[A-Z]/.test(v))) lvl = 3;
        if (v.length >= 16 && /[^A-Za-z0-9]/.test(v)) lvl = 4;
      }
      bar.style.setProperty('--w', ((lvl + 1) * 20) + '%');
      bar.style.setProperty('--c', colors[lvl]);
      label.textContent = ok ? names[lvl] : names[lvl] + ' · ' + hint;
    });
  });
})();
