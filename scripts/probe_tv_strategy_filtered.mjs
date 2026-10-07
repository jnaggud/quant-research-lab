#!/usr/bin/env node
import { evaluate, disconnect } from '../tradingview-mcp/src/connection.js';

const result = await evaluate(`
(function() {
  function safeCall(fn, fallback) {
    try { return fn(); } catch(e) { return fallback; }
  }
  function methodNames(obj) {
    var out = [];
    var seen = {};
    var proto = obj;
    for (var depth = 0; proto && depth < 6; depth++, proto = Object.getPrototypeOf(proto)) {
      safeCall(function() {
        Object.getOwnPropertyNames(proto).forEach(function(k) {
          if (!seen[k] && typeof obj[k] === 'function') {
            seen[k] = true;
            out.push(k);
          }
        });
      }, null);
    }
    return out;
  }
  function summarizeValue(v) {
    var t = Array.isArray(v) ? 'array' : typeof v;
    var out = {type: t};
    if (Array.isArray(v)) {
      out.length = v.length;
      out.first = v.length ? summarizeObject(v[0]) : null;
    } else if (v && typeof v === 'object') {
      out.keys = Object.keys(v).slice(0, 80);
    }
    return out;
  }
  function summarizeObject(obj) {
    if (!obj || typeof obj !== 'object') return obj;
    var out = {};
    Object.keys(obj).slice(0, 80).forEach(function(k) {
      var v = obj[k];
      if (v === null || v === undefined || typeof v === 'function') return;
      if (typeof v === 'object') out[k] = summarizeValue(v);
      else out[k] = v;
    });
    return out;
  }
  try {
    var chart = window.TradingViewApi._activeChartWidgetWV.value()._chartWidget;
    var model = chart.model().model();
    var sources = model.dataSources();
    var rows = [];
    var includeRe = /(JD ES 15m Risk|Backtest Adapter|strategy|report|ordersData|tradesData|equityData|profit|backtest|tester|broker|closed|position|tradeList|orderList)/i;
    var skipRe = /(^_|zorder|zOrder|preferredZOrder|setZorder|SpeciallyZOrdered|priceScale|pane|legend|watermark|autoscale|selection|magnet|interval|style|formatter|font|lineTool)/i;
    var targetIds = {'087vOT': true, 'rM1UHE': true};
    for (var i = 0; i < sources.length; i++) {
      var s = sources[i];
      var meta = safeCall(function(){ return s.metaInfo ? s.metaInfo() : null; }, null);
      var name = meta ? (meta.description || meta.shortDescription || '') : safeCall(function(){ return s.name ? s.name() : ''; }, '');
      var id = safeCall(function(){ return s.id ? String(s.id()) : String(s._id || ''); }, '');
      var title = safeCall(function(){ return s.title ? String(s.title()) : ''; }, '');
      var owner = safeCall(function(){ return s.ownerSource ? String(s.ownerSource()) : ''; }, '');
      var keys = safeCall(function(){ return Object.keys(s); }, []);
      var methods = methodNames(s);
      var hits = keys.concat(methods).filter(function(k){ return includeRe.test(k) && !skipRe.test(k); });
      var isTarget = !!targetIds[id] || includeRe.test(name) || includeRe.test(title) || hits.length;
      if (isTarget) {
        var probes = {};
        hits.slice(0, 80).forEach(function(k) {
          probes[k] = safeCall(function() {
            var v = s[k];
            if (typeof v === 'function') v = v.call(s);
            if (v && typeof v.value === 'function') v = v.value();
            return summarizeValue(v);
          }, {error: 'call failed'});
        });
        rows.push({
          index: i,
          id: id,
          name: name,
          title: title,
          owner: owner,
          meta: meta ? summarizeObject(meta) : null,
          hit_count: hits.length,
          keys: keys.filter(function(k){ return includeRe.test(k) && !skipRe.test(k); }).slice(0, 120),
          methods: methods.filter(function(k){ return includeRe.test(k) && !skipRe.test(k); }).slice(0, 120),
          probes: probes
        });
      }
    }
    var modelKeys = Object.keys(model).filter(function(k){ return includeRe.test(k) && !skipRe.test(k); }).slice(0, 120);
    var chartKeys = Object.keys(chart).filter(function(k){ return includeRe.test(k) && !skipRe.test(k); }).slice(0, 120);
    var bottom = safeCall(function() {
      var bwb = window.TradingView && window.TradingView.bottomWidgetBar;
      if (!bwb) return null;
      return {
        keys: Object.keys(bwb).filter(function(k){ return includeRe.test(k) && !skipRe.test(k); }).slice(0, 120),
        methods: methodNames(bwb).filter(function(k){ return includeRe.test(k) && !skipRe.test(k); }).slice(0, 120)
      };
    }, null);
    return {success: true, source_count: sources.length, matched_count: rows.length, model_keys: modelKeys, chart_keys: chartKeys, bottom_widget_bar: bottom, rows: rows};
  } catch(e) {
    return {success: false, error: e.message, stack: e.stack};
  }
})()
`);

console.log(JSON.stringify(result, null, 2));
await disconnect();
