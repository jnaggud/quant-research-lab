#!/usr/bin/env node
import { evaluate, disconnect } from '../tradingview-mcp/src/connection.js';

const result = await evaluate(`
(function() {
  try {
    var chart = window.TradingViewApi._activeChartWidgetWV.value()._chartWidget;
    var sources = chart.model().model().dataSources();
    var out = [];
    for (var i = 0; i < sources.length; i++) {
      var s = sources[i];
      var meta = null;
      try { meta = s.metaInfo ? s.metaInfo() : null; } catch(e) {}
      var name = meta ? (meta.description || meta.shortDescription || '') : '';
      var keys = [];
      try { keys = Object.keys(s).slice(0, 200); } catch(e) {}
      var methodNames = [];
      var proto = s;
      var seen = {};
      for (var depth = 0; proto && depth < 4; depth++, proto = Object.getPrototypeOf(proto)) {
        try {
          Object.getOwnPropertyNames(proto).forEach(function(k) {
            if (!seen[k] && typeof s[k] === 'function') {
              seen[k] = true;
              methodNames.push(k);
            }
          });
        } catch(e) {}
      }
      var interesting = {};
      ['ordersData','tradesData','reportData','performance','equityData','bars','_orders'].forEach(function(k) {
        try {
          var v = s[k];
          interesting[k] = typeof v;
          if (v && typeof v === 'object') {
            interesting[k + '_keys'] = Object.keys(v).slice(0, 50);
            if (typeof v.value === 'function') {
              var vv = v.value();
              interesting[k + '_value_type'] = Array.isArray(vv) ? 'array' : typeof vv;
              interesting[k + '_value_len'] = Array.isArray(vv) ? vv.length : null;
              interesting[k + '_value_keys'] = vv && typeof vv === 'object' && !Array.isArray(vv) ? Object.keys(vv).slice(0, 50) : null;
            }
          } else if (typeof v === 'function') {
            interesting[k + '_callable'] = true;
          }
        } catch(e) {
          interesting[k + '_error'] = e.message;
        }
      });
      out.push({
        index: i,
        name: name,
        id: s.id ? String(s.id()) : null,
        is_price_study: meta ? meta.is_price_study : null,
        keys: keys,
        methods: methodNames.slice(0, 200),
        interesting: interesting
      });
    }
    return {success: true, count: out.length, sources: out};
  } catch(e) {
    return {success: false, error: e.message, stack: e.stack};
  }
})()
`);

console.log(JSON.stringify(result, null, 2));
await disconnect();
