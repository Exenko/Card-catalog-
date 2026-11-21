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

// Two-sided scan: send whichever sides have been dropped to /ocr, which
// auto-crops each one, reads both, and returns a single merged suggestion.
(function () {
  var zones = { front: document.getElementById("drop-front"),
                back:  document.getElementById("drop-back") };
  if (!zones.front && !zones.back) return;

  var status = document.getElementById("ocr-status");
  var files = { front: null, back: null };

  function setField(name, value, onlyIfEmpty) {
    var el = document.querySelector('[name="' + name + '"]');
    if (!el || !value) return false;
    if (onlyIfEmpty && el.value.trim()) return false;
    el.value = value;
    return true;
  }

  // Mirror the dropped file into the real upload input so it gets saved.
  function mirror(side, file) {
    var input = document.getElementById("card-" + side + "-input");
    if (!input) return;
    try {
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
    } catch (e) { /* older browser: they can pick the file again below */ }
  }

  function showPreview(side, info, file) {
    var box = document.getElementById("prev-" + side);
    if (!box) return;
    var src = (info && info.preview) || URL.createObjectURL(file);
    box.innerHTML = "";
    var img = document.createElement("img");
    img.src = src;
    var tag = document.createElement("span");
    if (!info) {
      // Local preview, shown while the server is still looking for the card.
      img.alt = side + " of the card, being read";
      tag.className = "tag plain";
      tag.textContent = "scanning\u2026";
    } else {
      img.alt = (info.cropped ? "Auto-cropped " : "") + side + " of the card";
      tag.className = "tag" + (info.cropped ? "" : " plain");
      tag.textContent = info.cropped ? "auto-cropped" : "whole photo";
    }
    box.appendChild(img);
    box.appendChild(tag);
  }

  function scan() {
    if (!files.front && !files.back) return;
    var body = new FormData();
    if (files.front) body.append("front", files.front);
    if (files.back) body.append("back", files.back);
    var toggle = document.getElementById("autocrop");
    body.append("autocrop", toggle && !toggle.checked ? "0" : "1");

    status.innerHTML = '<span class="spinner"></span>Reading the card\u2026';
    fetch("/ocr", { method: "POST", body: body })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error && !d.sides) { status.textContent = "Couldn't read it: " + d.error; return; }

        var sides = d.sides || {};
        var problems = [];
        ["front", "back"].forEach(function (side) {
          if (!files[side]) return;
          var info = sides[side];
          if (info && info.error) { problems.push(side + ": " + info.error); return; }
          showPreview(side, info, files[side]);
        });

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
              window.ccAddLink(l.label, l.url);
              existing.push(l.url.toLowerCase());
              added++;
            }
          });
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

        var msg = filled.length
          ? "Filled in " + filled.join(", ") + ". Check it over before saving."
          : "Couldn't make out any fields \u2014 the raw text is below, and you "
            + "can type the details in.";
        if (!files.back && files.front) {
          msg += " Add the back too \u2014 that's usually where the links are.";
        }
        if (problems.length) msg += " (" + problems.join("; ") + ")";
        status.textContent = msg;
      })
      .catch(function () { status.textContent = "OCR request failed."; });
  }

  function accept(side, file) {
    if (!file) return;
    if (!/^image\//.test(file.type)) {
      status.textContent = "That file isn't an image.";
      return;
    }
    files[side] = file;
    mirror(side, file);
    showPreview(side, null, file);
    scan();
  }

  ["front", "back"].forEach(function (side) {
    var zone = zones[side];
    if (!zone) return;
    var input = document.getElementById("pick-" + side);
    if (input) {
      input.addEventListener("change", function () { accept(side, input.files[0]); });
    }
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
      if (e.dataTransfer.files && e.dataTransfer.files.length) {
        accept(side, e.dataTransfer.files[0]);
      }
    });
  });

  // Changing the crop setting re-reads whatever has already been dropped.
  var toggle = document.getElementById("autocrop");
  if (toggle) toggle.addEventListener("change", scan);
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
