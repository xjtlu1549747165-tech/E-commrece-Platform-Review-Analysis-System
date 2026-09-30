(function () {
  function getTrackElements(grid) {
    if (!grid) return [];
    return Array.prototype.slice.call(grid.querySelectorAll("[data-track]"));
  }

  function initPage(page) {
    if (!page) return;
    var storageKey = page.dataset.storageKey;
    var max = parseInt(page.dataset.max || "3", 10);
    var defaultTrack = page.dataset.defaultTrack || "dse";
    var grid = page.querySelector(".overview-grid") || page.querySelector(".figures-grid");
    var checkboxes = page.querySelectorAll(".track-picker input[type=checkbox]");
    var trackEls = getTrackElements(grid);

    function loadSelection() {
      try {
        var raw = localStorage.getItem(storageKey);
        if (raw) {
          var arr = JSON.parse(raw);
          if (Array.isArray(arr) && arr.length) return arr;
        }
      } catch (e) {}
      var avail = trackEls.map(function (e) {
        return e.getAttribute("data-track");
      });
      if (avail.indexOf(defaultTrack) >= 0) return [defaultTrack];
      return avail.length ? [avail[0]] : [];
    }

    function saveSelection(sel) {
      try {
        localStorage.setItem(storageKey, JSON.stringify(sel));
      } catch (e) {}
    }

    function applyGridColumns(n) {
      if (!grid) return;
      if (n <= 1) grid.style.gridTemplateColumns = "1fr";
      else grid.style.gridTemplateColumns = "repeat(" + n + ", 1fr)";
    }

    function syncFromChecks() {
      var sel = [];
      checkboxes.forEach(function (cb) {
        if (cb.checked) sel.push(cb.value);
      });
      trackEls.forEach(function (el) {
        var t = el.getAttribute("data-track");
        el.style.display = sel.indexOf(t) >= 0 ? "" : "none";
      });
      applyGridColumns(sel.length);
      saveSelection(sel);
    }

    var sel = loadSelection();
    var avail = trackEls.map(function (e) {
      return e.getAttribute("data-track");
    });
    sel = sel.filter(function (t) {
      return avail.indexOf(t) >= 0;
    });
    if (!sel.length && avail.length) sel = [avail[0]];

    checkboxes.forEach(function (cb) {
      cb.checked = sel.indexOf(cb.value) >= 0;
    });

    checkboxes.forEach(function (cb) {
      cb.addEventListener("change", function () {
        var picked = [];
        checkboxes.forEach(function (c) {
          if (c.checked) picked.push(c.value);
        });
        if (picked.length > max) {
          cb.checked = false;
          window.alert("You can select at most " + max + " track(s) on this page.");
          return;
        }
        if (picked.length === 0) {
          cb.checked = true;
          window.alert("Select at least one track.");
          return;
        }
        syncFromChecks();
      });
    });

    syncFromChecks();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initPage(document.getElementById("overview-page"));
    initPage(document.getElementById("figures-page"));
  });
})();
