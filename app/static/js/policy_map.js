/**
 * China map: only Hong Kong SAR (adcode 810000) is interactive; others are grey/silent.
 * Depends on: window.__POLICY_GEO_URL__, echarts global.
 */
(function () {
  function $(id) {
    return document.getElementById(id);
  }

  function normalize(s) {
    return (s || "").toLowerCase().trim();
  }

  function filterDocList(query) {
    var q = normalize(query);
    var items = document.querySelectorAll(".policy-doc-item");
    items.forEach(function (li) {
      var t = normalize(li.getAttribute("data-title-en") || "");
      li.style.display = !q || t.indexOf(q) !== -1 ? "" : "none";
    });
  }

  function showRegionPanel() {
    var intro = $("policy-intro");
    var panel = $("region-panel");
    if (intro) intro.classList.add("hidden");
    if (panel) panel.classList.remove("hidden");
    var search = $("policy-search");
    if (search) {
      search.disabled = false;
      search.value = "";
      search.placeholder = "Filter by English title…";
      filterDocList("");
    }
  }

  window.PolicyPage = {
    selectHongKong: function () {
      showRegionPanel();
    },
    filterDocs: filterDocList,
  };

  function initChart() {
    var el = $("policy-map");
    var geoUrl = window.__POLICY_GEO_URL__;
    if (!el || !geoUrl || typeof echarts === "undefined") return;

    var chart = echarts.init(el);
    fetch(geoUrl)
      .then(function (r) {
        return r.json();
      })
      .then(function (geoJson) {
        var hkName = null;
        geoJson.features.forEach(function (f) {
          if (f.properties && f.properties.adcode === 810000) {
            hkName = f.properties.name;
          }
        });

        echarts.registerMap("chinaPolicy", geoJson);

        var regions = geoJson.features.map(function (f) {
          var ad = f.properties.adcode;
          var name = f.properties.name;
          var en = ad === 810000;
          return {
            name: name,
            silent: !en,
            itemStyle: {
              areaColor: en ? "#3d6fb5" : "#343d4d",
              borderColor: "#2c3b52",
            },
            emphasis: {
              disabled: !en,
              itemStyle: en ? { areaColor: "#5a8fd4" } : { areaColor: "#343d4d" },
            },
            select: {
              disabled: true,
            },
          };
        });

        chart.setOption({
          tooltip: {
            trigger: "item",
            show: true,
            formatter: function (params) {
              if (!params.name) return "";
              if (params.name === hkName) {
                return params.name + "<br/><span style='opacity:.85'>Click to view documents</span>";
              }
              return params.name + "<br/><span style='opacity:.75'>No prototype documents</span>";
            },
          },
          geo: {
            map: "chinaPolicy",
            roam: true,
            zoom: 1.1,
            regions: regions,
            itemStyle: {
              borderColor: "#2c3b52",
            },
          },
        });

        chart.on("click", function (params) {
          if (params.componentType === "geo" && hkName && params.name === hkName) {
            window.PolicyPage.selectHongKong();
          }
        });

        window.addEventListener("resize", function () {
          chart.resize();
        });
      })
      .catch(function (err) {
        console.error("Policy map geo load failed", err);
        el.innerHTML =
          "<p class='err'>Could not load map data. Ensure app/static/geo/china_100000_full.json exists.</p>";
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = $("policy-refresh-btn");
    if (btn) {
      btn.addEventListener("click", function () {
        window.location.reload();
      });
    }
    var search = $("policy-search");
    if (search) {
      search.addEventListener("input", function () {
        filterDocList(search.value);
      });
    }
    initChart();
  });
})();
