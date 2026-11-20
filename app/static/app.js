// Theme toggle -- remembers the choice per browser.
(function () {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var root = document.documentElement;
    var current = root.getAttribute("data-theme");
    if (!current) {
      current = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark" : "light";
    }
    var next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("cc-theme", next); } catch (e) {}
  });
})();

// Repeatable link rows on the artist form.
(function () {
  var list = document.getElementById("link-list");
  var add = document.getElementById("add-link");
  if (!list || !add) return;

  function blankRow(label, url) {
    var row = document.createElement("div");
    row.className = "link-row";
    row.innerHTML =
      '<input type="text" name="link_label" placeholder="Label (Shop, Instagram...)">' +
      '<input type="text" name="link_url" placeholder="https://...">' +
      '<button type="button" class="btn btn-sm btn-danger remove-link" ' +
      'aria-label="Remove this link">Remove</button>';
    if (label) row.children[0].value = label;
    if (url) row.children[1].value = url;
    return row;
  }
  add.addEventListener("click", function () {
    var row = blankRow();
    list.appendChild(row);
    row.children[1].focus();
  });
  list.addEventListener("click", function (e) {
    if (e.target.classList.contains("remove-link")) {
      e.target.closest(".link-row").remove();
    }
  });
  window.ccAddLink = function (label, url) { list.appendChild(blankRow(label, url)); };
})();

// OCR assist: send the card photo to /ocr, pre-fill whatever comes back.
(function () {
  var zone = document.getElementById("ocr-drop");
  var input = document.getElementById("ocr-input");
  var status = document.getElementById("ocr-status");
  var preview = document.getElementById("ocr-preview");
  if (!zone || !input) return;

  function setField(name, value, onlyIfEmpty) {
    var el = document.querySelector('[name="' + name + '"]');
    if (!el || !value) return false;
    if (onlyIfEmpty && el.value.trim()) return false;
    el.value = value;
    return true;
  }

  function showPreview(file) {
    if (!preview) return;
    var url = URL.createObjectURL(file);
    preview.innerHTML = '<img alt="Card preview just uploaded">';
    preview.firstChild.src = url;
  }

  function run(file) {
    if (!file) return;
    if (!/^image\//.test(file.type)) {
      status.textContent = "That file isn't an image.";
      return;
    }
    showPreview(file);
    status.innerHTML = '<span class="spinner"></span>Reading the card...';

    // Hand the same photo to the real form field so it gets saved as the cover.
    var frontField = document.getElementById("card-front-input");
    if (frontField) {
      try {
        var dt = new DataTransfer();
        dt.items.add(file);
        frontField.files = dt.files;
      } catch (e) { /* older browser: user can pick the file again below */ }
    }

    var body = new FormData();
    body.append("card", file);
    fetch("/ocr", { method: "POST", body: body })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { status.textContent = "Couldn't read it: " + d.error; return; }
        var filled = [];
        if (setField("name", d.name, true)) filled.push("name");
        if (setField("handle", d.handle, true)) filled.push("handle");
        if (setField("shop_name", d.shop_name, true)) filled.push("shop");
        if (d.tags && d.tags.length && setField("tags", d.tags.join(", "), true)) {
          filled.push("tags");
        }
        setField("ocr_text", d.raw_text || "", false);

        if (d.links && d.links.length && window.ccAddLink) {
          var existing = Array.prototype.map.call(
            document.querySelectorAll('[name="link_url"]'),
            function (i) { return i.value.trim().toLowerCase(); });
          var added = 0;
          d.links.forEach(function (l) {
            if (existing.indexOf(l.url.toLowerCase()) === -1) {
              window.ccAddLink(l.label, l.url); added++;
            }
          });
          // Drop any empty starter rows now that we have real links.
          if (added) {
            document.querySelectorAll("#link-list .link-row").forEach(function (row) {
              if (!row.children[1].value.trim()) row.remove();
            });
            filled.push(added + (added === 1 ? " link" : " links"));
          }
        }
        if (d.email) {
          var notes = document.querySelector('[name="notes"]');
          if (notes && notes.value.indexOf(d.email) === -1) {
            notes.value = (notes.value ? notes.value + "\n" : "") + d.email;
            filled.push("email");
          }
        }
        var raw = document.getElementById("ocr-raw");
        if (raw) raw.textContent = d.raw_text || "(nothing readable)";
        var rawBox = document.getElementById("ocr-raw-box");
        if (rawBox) rawBox.hidden = !d.raw_text;

        status.textContent = filled.length
          ? "Filled in " + filled.join(", ") + ". Check it over before saving."
          : "Couldn't make out any fields — the raw text is below, and you can type the details in.";
      })
      .catch(function () { status.textContent = "OCR request failed."; });
  }

  input.addEventListener("change", function () { run(input.files[0]); });
  ["dragenter", "dragover"].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault(); zone.classList.add("hot");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault(); zone.classList.remove("hot");
    });
  });
  zone.addEventListener("drop", function (e) {
    if (e.dataTransfer.files && e.dataTransfer.files.length) run(e.dataTransfer.files[0]);
  });
})();

// Copy-to-clipboard for the share link.
(function () {
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = document.querySelector(btn.getAttribute("data-copy"));
      if (!target) return;
      target.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) {}
      if (navigator.clipboard) { navigator.clipboard.writeText(target.value); ok = true; }
      btn.textContent = ok ? "Copied" : "Press Ctrl+C";
      setTimeout(function () { btn.textContent = "Copy"; }, 1800);
    });
  });
})();

// Live budget meter on the wish list.
(function () {
  var input = document.getElementById("budget-input");
  if (!input) return;
  var form = input.closest("form");
  var t = null;
  input.addEventListener("input", function () {
    clearTimeout(t);
    t = setTimeout(function () { form.submit(); }, 600);
  });
})();
