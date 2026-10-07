#!/usr/bin/env node
import { evaluateAsync, disconnect } from '../tradingview-mcp/src/connection.js';

const loops = Number(process.argv[2] || 20);
const delayMs = Number(process.argv[3] || 750);

const result = await evaluateAsync(`
(async function() {
  function snapshot(label) {
    var widget = window.TradingViewApi._activeChartWidgetWV.value();
    var model = widget._chartWidget.model();
    var main = model.mainSeries();
    var bars = main.bars();
    return {
      label: label,
      first_index: bars.firstIndex(),
      last_index: bars.lastIndex(),
      size: bars.size ? bars.size() : null,
      request_more_available: main.requestMoreDataAvailable ? main.requestMoreDataAvailable() : null,
      visible: (function(){ try { return widget.getVisibleRange(); } catch(e) { return null; } })()
    };
  }
  var widget = window.TradingViewApi._activeChartWidgetWV.value();
  var model = widget._chartWidget.model();
  var main = model.mainSeries();
  var ts = model.timeScale();
  var samples = [snapshot('before')];
  var errors = [];
  for (var i = 0; i < ${loops}; i++) {
    try {
      if (ts.scrollToFirstBar) ts.scrollToFirstBar();
    } catch (e) { errors.push('scrollToFirstBar: ' + e.message); }
    try {
      if (main.requestMoreData) main.requestMoreData();
    } catch (e) { errors.push('requestMoreData: ' + e.message); }
    try {
      if (ts.requestMoreHistoryPoints) ts.requestMoreHistoryPoints();
    } catch (e) { errors.push('requestMoreHistoryPoints: ' + e.message); }
    try {
      if (ts._requestMoreData) ts._requestMoreData();
    } catch (e) { errors.push('_requestMoreData: ' + e.message); }
    await new Promise(function(resolve) { setTimeout(resolve, ${delayMs}); });
    var snap = snapshot('loop_' + (i + 1));
    samples.push(snap);
    if (i > 2) {
      var prev = samples[samples.length - 2];
      if (snap.first_index === prev.first_index && snap.size === prev.size && snap.request_more_available === false) break;
    }
  }
  samples.push(snapshot('after'));
  return {success: true, loops_requested: ${loops}, delay_ms: ${delayMs}, errors: errors.slice(0, 20), samples: samples};
})()
`);

console.log(JSON.stringify(result, null, 2));
await disconnect();
