/**
 * Slim deterministic yad2 detail scraper for browser_eval.
 * Set window.__SCRAPE_TOKENS__ = [...] first, then eval this file.
 * Returns JSON string: {ok, fetched, errors, results:[{token,views,error,api}]}
 * api is slimmed to fields needed by scrape_listing_details.parse_api_item
 */
(function () {
  var tokens = window.__SCRAPE_TOKENS__ || [];
  var results = [];

  function xhrGet(url) {
    var x = new XMLHttpRequest();
    x.open("GET", url, false);
    x.setRequestHeader("Accept", "application/json, text/plain, */*");
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

  function slimApi(d) {
    return {
      ad_number: d.ad_number || d.adNumber || null,
      info_text: d.info_text || (d.metaData && d.metaData.description) || "",
      parking: d.parking != null ? d.parking : null,
      shelter: d.shelter != null ? d.shelter : (d.inProperty && d.inProperty.includeSecurityRoom),
      square_meters: d.square_meters || (d.additionalDetails && d.additionalDetails.squareMeter) || null,
      date_added: d.date_added || (d.dates && d.dates.createdAt) || "",
      date_raw: d.date_raw || (d.dates && d.dates.updatedAt) || "",
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
