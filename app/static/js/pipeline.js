(function () {
  var pollTimer = null;
  var currentJobId = null;

  function $(id) {
    return document.getElementById(id);
  }

  function setButtonsDisabled(disabled) {
    document.querySelectorAll(".btn-pipeline").forEach(function (btn) {
      btn.disabled = disabled;
    });
  }

  function showJobPanel(jobId) {
    $("job-panel").classList.remove("hidden");
    $("job-id-label").textContent = jobId;
    $("job-status-badge").textContent = "running";
    $("job-status-badge").className = "status-badge status-running";
    $("job-success-links").classList.add("hidden");
    $("job-log").textContent = "";
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function pollJob(jobId, jobType) {
    fetch("/api/jobs/" + encodeURIComponent(jobId))
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        $("job-log").textContent = data.log_tail || "";
        $("job-log").scrollTop = $("job-log").scrollHeight;
        $("job-status-badge").textContent = data.status || "";
        $("job-status-badge").className =
          "status-badge status-" + (data.status || "unknown");

        if (data.status === "running") {
          return;
        }
        stopPolling();
        setButtonsDisabled(false);

        if (data.status === "success") {
          if (jobType === "brief" && data.result && data.result.brief_id) {
            window.location.href = "/brief/" + encodeURIComponent(data.result.brief_id);
            return;
          }
          var links = $("job-success-links");
          links.classList.remove("hidden");
          if (jobType === "nlp" || jobType === "crawl" || jobType === "enrich") {
            links.innerHTML =
              'Done. <a href="/">Overview</a> · <a href="/figures">Figures</a>';
          } else {
            links.textContent = "Job completed successfully.";
          }
        } else if (data.status === "failed") {
          $("job-log").textContent +=
            "\n\n--- FAILED (exit " + (data.exit_code != null ? data.exit_code : "?") + ") ---\n" +
            (data.error || "");
        }
      })
      .catch(function (err) {
        console.error(err);
      });
  }

  function startJob(body) {
    setButtonsDisabled(true);
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, status: r.status, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          setButtonsDisabled(false);
          alert(res.data.error || "Failed to start job (" + res.status + ")");
          return;
        }
        currentJobId = res.data.job_id;
        showJobPanel(currentJobId);
        stopPolling();
        pollTimer = setInterval(function () {
          pollJob(currentJobId, body.type);
        }, 2000);
        pollJob(currentJobId, body.type);
      })
      .catch(function (err) {
        setButtonsDisabled(false);
        alert("Request failed: " + err);
      });
  }

  function loadTracks() {
    fetch("/api/pipeline/tracks")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var tracks = data.tracks || [];
        $("known-tracks").textContent = tracks.length ? tracks.join(", ") : "(none)";
        var box = $("brief-tracks");
        if (!tracks.length) {
          box.textContent = "No config/*_keywords.yaml found.";
          return;
        }
        box.innerHTML = "";
        tracks.forEach(function (t) {
          var label = document.createElement("label");
          label.className = "brief-track-check";
          var cb = document.createElement("input");
          cb.type = "checkbox";
          cb.name = "brief_track";
          cb.value = t;
          label.appendChild(cb);
          label.appendChild(document.createTextNode(" " + t));
          box.appendChild(label);
        });
      });
  }

  function loadChromeStatus() {
    fetch("/api/pipeline/chromium-status")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var el = $("chrome-status");
        if (data.reachable) {
          el.textContent = "Chromium debugger reachable at " + data.address;
          el.className = "chrome-status chrome-ok";
        } else {
          el.textContent =
            "Chromium not reachable at " +
            data.address +
            ". Start Chrome with remote debugging and log in to Xiaohongshu before crawl/enrich.";
          el.className = "chrome-status chrome-bad";
          $("btn-crawl").disabled = true;
          $("btn-enrich").disabled = true;
        }
      });
  }

  function selectedBriefTracks() {
    var out = [];
    document.querySelectorAll('input[name="brief_track"]:checked').forEach(function (cb) {
      out.push(cb.value);
    });
    return out;
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadTracks();
    loadChromeStatus();

    $("btn-crawl").addEventListener("click", function () {
      var track = ($("crawl-track").value || "").trim();
      if (!track) {
        alert("Enter a track id.");
        return;
      }
      startJob({ type: "crawl", track: track });
    });

    $("btn-enrich").addEventListener("click", function () {
      var track = ($("enrich-track").value || "").trim();
      if (!track) {
        alert("Enter a track id.");
        return;
      }
      var body = { type: "enrich", track: track };
      var lim = $("enrich-limit").value;
      if (lim) body.limit = parseInt(lim, 10);
      startJob(body);
    });

    $("btn-nlp").addEventListener("click", function () {
      var track = ($("nlp-track").value || "all").trim();
      startJob({ type: "nlp", track: track || "all" });
    });

    $("btn-brief").addEventListener("click", function () {
      var tracks = selectedBriefTracks();
      if (!tracks.length) {
        alert("Select at least one track for the brief.");
        return;
      }
      startJob({ type: "brief", tracks: tracks });
    });

    fetch("/api/jobs/active")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.active && data.active.status === "running") {
          currentJobId = data.active.job_id;
          setButtonsDisabled(true);
          showJobPanel(currentJobId);
          pollTimer = setInterval(function () {
            pollJob(currentJobId, data.active.type);
          }, 2000);
          pollJob(currentJobId, data.active.type);
        }
      });
  });
})();
