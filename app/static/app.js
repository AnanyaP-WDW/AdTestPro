/* AdTestPro client behavior. Own-file only: no inline handlers, no remote deps. */
(function () {
  "use strict";

  /* ---------------------------------------------------------- theme */
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    var syncPressed = function () {
      themeBtn.setAttribute("aria-pressed", document.documentElement.classList.contains("dark"));
    };
    syncPressed();
    themeBtn.addEventListener("click", function () {
      var dark = document.documentElement.classList.toggle("dark");
      try { localStorage.setItem("adtestpro-theme", dark ? "dark" : "light"); } catch (e) { /* private mode */ }
      syncPressed();
    });
  }

  /* ------------------------------------------------- form behaviors */
  var form = document.getElementById("eval-form");
  if (!form) return;

  var fileInput = document.getElementById("image");
  var preview = document.getElementById("image-preview");
  var previewImg = document.getElementById("image-preview-img");
  var previewMeta = document.getElementById("image-preview-meta");
  var fileInfo = document.getElementById("file-info");
  var errorBox = document.getElementById("form-summary");  var submitBtn = document.getElementById("submit-btn");
  var pending = document.getElementById("pending");
  var elapsed = document.getElementById("pending-elapsed");
  var summarySlot = document.getElementById("run-summary");
  var MAX_BYTES = 15 * 1024 * 1024;

  /* image preview + client-side file rules */
  if (fileInput) {
    fileInput.addEventListener("change", function (e) {
      var f = e.target.files && e.target.files[0];
      if (!f) { hidePreview(); return; }
      if (f.type !== "image/png" && f.type !== "image/jpeg") {
        setFileNotice("Please select a PNG or JPEG image.");
        e.target.value = "";
        hidePreview();
        return;
      }
      if (f.size > MAX_BYTES) {
        setFileNotice("File exceeds the 15MB limit.");
        e.target.value = "";
        hidePreview();
        return;
      }
      setFileNotice("");
      showPreview(f);
    });
  }

  function setFileNotice(msg) {
    if (!fileInfo) return;
    fileInfo.textContent = msg;
    fileInfo.hidden = !msg;
  }

  function showPreview(f) {
    if (!preview || !previewImg || !previewMeta) return;
    previewImg.src = URL.createObjectURL(f);
    previewMeta.innerHTML = "";
    var name = document.createElement("strong");
    name.textContent = f.name;
    previewMeta.appendChild(name);
    previewMeta.appendChild(document.createTextNode(
      " — " + (f.size / 1048576).toFixed(2) + " MB" +
      (f.size > 4 * 1024 * 1024 ? " (large files upload slower)" : "")));
    preview.classList.add("is-visible");
  }

  function hidePreview() {
    if (!preview) return;
    preview.classList.remove("is-visible");
    if (previewImg) previewImg.src = "";
  }

  /* question limit: explain instead of silently undoing */
  var boxes = Array.prototype.slice.call(
    form.querySelectorAll('input[type="checkbox"][name="question_ids"]'));
  boxes.forEach(function (b) {
    b.addEventListener("change", function () {
      var checked = form.querySelectorAll('input[name="question_ids"]:checked').length;
      if (checked > 3) {
        b.checked = false;
        setFieldError(b, "Up to 3 questions per run. Unselect one to add another.");
      } else {
        clearFieldError(b);
      }
      updateSummary();
    });
  });

  /* run summary near the CTA */
  function updateSummary() {
    if (!summarySlot) return;
    var checked = form.querySelectorAll('input[name="question_ids"]:checked').length;
    var panel = document.getElementById("persona_count");
    var n = panel ? parseInt(panel.value, 10) || 0 : 0;
    var parts = [];
    parts.push(checked ? checked + (checked === 1 ? " question" : " questions") : "no questions");
    if (n >= 1 && n <= 25) parts.push("panel of " + n);
    summarySlot.textContent = parts.length ? parts.join(" · ") + " selected" : "";
  }
  form.addEventListener("change", updateSummary);
  updateSummary();

  /* field errors */
  function setFieldError(control, msg) {
    control.setAttribute("aria-invalid", "true");
    var holder = control.closest(".field, .choice, fieldset");
    if (!holder) return;
    var out = holder.querySelector(".field__error");
    if (!out) {
      out = document.createElement("p");
      out.className = "field__error";
      holder.appendChild(out);
    }
    out.textContent = msg;
  }

  function clearFieldError(control) {
    control.removeAttribute("aria-invalid");
    var holder = control.closest(".field, .choice, fieldset");
    if (!holder) return;
    var out = holder.querySelector(".field__error");
    if (out) out.remove();
  }

  /* validation parity with the server */
  function validate() {
    var errs = [];

    function flag(el, msg) {
      errs.push({ el: el, msg: msg });
      setFieldError(el, msg);
    }

    form.querySelectorAll("[aria-invalid]").forEach(clearFieldError);

    if (fileInput && !fileInput.files.length) {
      flag(fileInput, "Attach the ad image (PNG or JPEG).");
    }
    var ageMin = document.getElementById("age_min");
    var ageMax = document.getElementById("age_max");
    var mn = ageMin ? parseInt(ageMin.value, 10) : NaN;
    var mx = ageMax ? parseInt(ageMax.value, 10) : NaN;
    if (ageMin && (isNaN(mn) || mn < 13 || mn > 100)) flag(ageMin, "Min age must be 13–100.");
    if (ageMax && (isNaN(mx) || mx < 13 || mx > 100)) flag(ageMax, "Max age must be 13–100.");
    if (!isNaN(mn) && !isNaN(mx) && mn > mx) flag(ageMax, "Max age must be ≥ min age.");

    var required = ["product_description", "campaign_objective", "location", "interests", "pain_points"];
    required.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !el.value.trim()) flag(el, "This field is required.");
    });

    if (!form.querySelector('input[name="question_ids"]:checked')) {
      var first = boxes[0];
      if (first) flag(first, "Select at least one question.");
    }
    var pc = document.getElementById("persona_count");
    if (pc) {
      var n = parseInt(pc.value, 10);
      if (isNaN(n) || n < 1 || n > 25) flag(pc, "Panel size must be 1–25.");
    }
    return errs;
  }

  function renderErrorSummary(errs) {
    if (!errorBox) return;
    errorBox.innerHTML = "";
    var p = document.createElement("p");
    p.className = "alert__title";
    p.textContent = errs.length === 1
      ? "1 field needs attention"
      : errs.length + " fields need attention";
    errorBox.appendChild(p);
    var ul = document.createElement("ul");
    errs.forEach(function (e, i) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#";
      a.textContent = e.msg;
      a.addEventListener("click", function (ev) {
        ev.preventDefault();
        e.el.focus();
      });
      li.appendChild(a);
      ul.appendChild(li);
      e.el.setAttribute("aria-invalid", "true");
    });
    errorBox.appendChild(ul);
    errorBox.hidden = false;
  }

  form.addEventListener("submit", function (e) {
    var errs = validate();
    if (errs.length) {
      e.preventDefault();
      renderErrorSummary(errs);
      var first = errorBox && errorBox.querySelector("a");
      if (first) first.focus();
      return;
    }
    if (errorBox) errorBox.hidden = true;
    /* honest pending state: no stage claims, single announcement, focus moved */
    if (submitBtn) submitBtn.disabled = true;
    form.hidden = true;
    if (pending) {
      pending.classList.add("is-visible");
      var h = pending.querySelector(".pending__title");
      if (h) {
        h.setAttribute("id", "pending-title");
        h.setAttribute("tabindex", "-1");
        h.focus();
      }
    }
    if (elapsed) {
      var t0 = Date.now();
      setInterval(function () {
        elapsed.textContent = Math.floor((Date.now() - t0) / 1000) + "s elapsed";
      }, 1000);
    }
  });
})();
