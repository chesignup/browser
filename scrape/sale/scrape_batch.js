/**
 * yad2 detail scraper — set window.__SCRAPE_TOKENS__ and window.__SCRAPE_LINKS__ first.
 * Returns JSON: {ok, fetched, errors, results:[{token,views,error,api}]}
 */
(function () {
  var tokens = window.__SCRAPE_TOKENS__ || [];
  var links = window.__SCRAPE_LINKS__ || {};
  var results = [];

  function xhrGet(url) {
    var x = new XMLHttpRequest();
    x.open("GET", url, false);
    x.setRequestHeader("Accept", "application/json, text/plain, text/html, */*");
    x.send(null);
    return { status: x.status, text: x.responseText };
  }

  function isHtml(text) {
    return /^\s*</.test(text || "");
  }

  function slimAmen(items) {
    var out = [];
    (items || []).forEach(function (it) {
      if (it && (it.key === "elevator" || it.key === "shelter")) {
        out.push({ key: it.key, value: !!it.value });
      }
    });
    return out;
  }

  function pickDescription(d) {
    var parts = [
      d.info_text,
      d.metaData && d.metaData.description,
      d.inProperty && d.inProperty.description,
      d.description
    ];
    for (var i = 0; i < parts.length; i++) {
      if (parts[i] && String(parts[i]).trim()) {
        return String(parts[i]).trim();
      }
    }
    return "";
  }

  function pickCreatedAt(d) {
    if (d.date_added && String(d.date_added).trim()) return String(d.date_added).trim();
    if (d.dates && d.dates.createdAt) return String(d.dates.createdAt).trim();
    if (d.createdAt && String(d.createdAt).trim()) return String(d.createdAt).trim();
    return "";
  }

  function pickUpdatedAt(d) {
    if (d.date_raw && String(d.date_raw).trim()) return String(d.date_raw).trim();
    if (d.dates && d.dates.updatedAt) return String(d.dates.updatedAt).trim();
    if (d.updatedAt && String(d.updatedAt).trim()) return String(d.updatedAt).trim();
    return "";
  }

  function decodeHtmlEntities(s) {
    var t = document.createElement("textarea");
    t.innerHTML = s;
    return t.value;
  }

  function descriptionFromHtml(html) {
    if (!html) return "";
    var m = html.match(/data-testid=["']property-description["'][^>]*>([\s\S]*?)<\/p>/i);
    if (m && m[1]) {
      var text = m[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      if (text) return decodeHtmlEntities(text);
    }
    var scripts = html.match(/<script[^>]*>([\s\S]*?)<\/script>/gi) || [];
    for (var si = 0; si < scripts.length; si++) {
      var body = scripts[si].replace(/^<script[^>]*>/i, "").replace(/<\/script>$/i, "");
      if (body.indexOf("dehydratedState") === -1 && body.indexOf("info_text") === -1) continue;
      try {
        var data = JSON.parse(body);
        var queries = (((data.props || {}).pageProps || {}).dehydratedState || {}).queries || [];
        for (var qi = 0; qi < queries.length; qi++) {
          var item = queries[qi].state && queries[qi].state.data;
          if (!item) continue;
          var desc = pickDescription(item);
          if (desc) return desc;
        }
      } catch (e) {}
      var m2 = body.match(/"info_text"\s*:\s*"((?:\\.|[^"\\])*)"/);
      if (m2) {
        try { return JSON.parse('"' + m2[1] + '"'); } catch (e2) {}
      }
    }
    return "";
  }

  function fetchDomDescription(link) {
    if (!link) return "";
    try {
      var res = xhrGet(link);
      if (res.status === 200 && res.text) {
        return descriptionFromHtml(res.text);
      }
    } catch (e) {}
    return "";
  }

  function slimApi(d) {
    var infoText = pickDescription(d);
    return {
      ad_number: d.ad_number || d.adNumber || null,
      info_text: infoText,
      description: infoText,
      metaData: d.metaData || null,
      inProperty: d.inProperty || null,
      parking: d.parking != null ? d.parking : null,
      shelter: d.shelter != null ? d.shelter : (d.inProperty && d.inProperty.includeSecurityRoom),
      square_meters: d.square_meters || (d.additionalDetails && d.additionalDetails.squareMeter) || null,
      date_added: pickCreatedAt(d),
      date_raw: pickUpdatedAt(d),
      dates: d.dates || null,
      price: d.price,
      additional_info_items_v2: slimAmen(d.additional_info_items_v2) || [
        { key: "elevator", value: null },
        { key: "shelter", value: !!(d.inProperty && d.inProperty.includeSecurityRoom) }
      ],
      info_bar_items: d.info_bar_items || null,
      city_text: d.city_text || (d.address && d.address.city && d.address.city.text) || ""
    };
  }

  for (var i = 0; i < tokens.length; i++) {
    var token = tokens[i];
    var row = { token: token, views: null, api: null, error: null };
    try {
      var itemRes = xhrGet("https://www.yad2.co.il/api/item/" + token);
      if (itemRes.status === 200 && !isHtml(itemRes.text)) {
        row.api = slimApi(JSON.parse(itemRes.text));
      } else {
        var gw = xhrGet("https://gw.yad2.co.il/realestate-item/" + token);
        if (gw.status === 200 && !isHtml(gw.text)) {
          var gwData = JSON.parse(gw.text);
          row.api = slimApi(gwData.data || gwData);
        } else {
          row.error = "item_http_" + itemRes.status + "_gw_" + gw.status;
          results.push(row);
          continue;
        }
      }
      if (row.api && !row.api.info_text) {
        var domDesc = fetchDomDescription(links[token]);
        if (domDesc) {
          row.api.info_text = domDesc;
          row.api.description = domDesc;
          row.api.dom_description = domDesc;
        }
      }
      try {
        var viewsRes = xhrGet("https://gw.yad2.co.il/ad-seen-count/" + token);
        if (viewsRes.status === 200 && !isHtml(viewsRes.text)) {
          var v = JSON.parse(viewsRes.text);
          row.views = (v.data && v.data.seenCount != null) ? v.data.seenCount : null;
        }
      } catch (ve) {}
    } catch (e) {
      row.error = String(e && e.message ? e.message : e);
    }
    results.push(row);
  }

  window.__SCRAPE_LAST__ = results;
  var ok = results.filter(function (r) { return !r.error && r.api; }).length;
  return JSON.stringify({ ok: ok, fetched: results.length, errors: results.length - ok, results: results });
})();
