#!/usr/bin/env node
import { evaluate, disconnect } from '../tradingview-mcp/src/connection.js';

const targetId = process.argv[2] || process.env.TRADINGVIEW_STRATEGY_ID || '';
const targetName = process.argv[3] || process.env.TRADINGVIEW_STRATEGY_NAME || 'JD ES 15m C11';

const result = await evaluate(`
(function() {
  function safeCall(fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
  }
  function resolve(v) {
    if (typeof v === 'function') v = v();
    if (v && typeof v.value === 'function') v = v.value();
    return v;
  }
  function plain(v, depth) {
    if (v === null || v === undefined) return v;
    if (depth <= 0) {
      if (Array.isArray(v)) return {type: 'array', length: v.length};
      if (typeof v === 'object') return {type: 'object', keys: Object.keys(v).slice(0, 80)};
      return v;
    }
    if (Array.isArray(v)) return v.map(function(x) { return plain(x, depth - 1); });
    if (typeof v === 'object') {
      var out = {};
      Object.keys(v).forEach(function(k) {
        var x = v[k];
        if (typeof x === 'function') return;
        out[k] = plain(x, depth - 1);
      });
      return out;
    }
    return v;
  }
  try {
    var chart = window.TradingViewApi._activeChartWidgetWV.value()._chartWidget;
    var model = chart.model().model();
    var sources = model.dataSources();
    var wantedId = ${JSON.stringify(targetId)};
    var wantedName = ${JSON.stringify(targetName)};
    var candidates = [];
    for (var i = 0; i < sources.length; i++) {
      var s = sources[i];
      var id = safeCall(function(){ return s.id ? String(s.id()) : String(s._id || ''); }, '');
      var meta = safeCall(function(){ return s.metaInfo ? s.metaInfo() : null; }, null);
      var name = meta ? (meta.description || meta.shortDescription || '') : safeCall(function(){ return s.name ? s.name() : ''; }, '');
      var title = safeCall(function(){ return s.title ? String(s.title()) : ''; }, '');
      if (id === wantedId || name.indexOf(wantedName) !== -1 || title.indexOf(wantedName) !== -1) {
        candidates.push({index: i, id: id, name: name, title: title, source: s, meta: meta});
      }
    }
    if (!candidates.length) return {success: false, error: 'C5 source not found', source_count: sources.length};
    var c = candidates[0];
    var reportData = c.source.reportData ? resolve(c.source.reportData.bind(c.source)) : null;
    var ordersData = c.source.ordersData ? resolve(c.source.ordersData.bind(c.source)) : null;
    return {
      success: true,
      source: {
        index: c.index,
        id: c.id,
        name: c.name,
        title: c.title,
        meta: plain(c.meta, 2)
      },
      reportData: plain(reportData, 6),
      ordersData: plain(ordersData, 4)
    };
  } catch (e) {
    return {success: false, error: e.message, stack: e.stack};
  }
})()
`);

console.log(JSON.stringify(result, null, 2));
await disconnect();
