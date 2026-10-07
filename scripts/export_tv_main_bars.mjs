#!/usr/bin/env node
import { evaluate, disconnect } from '../tradingview-mcp/src/connection.js';

const result = await evaluate(`
(function() {
  try {
    var widget = window.TradingViewApi._activeChartWidgetWV.value();
    var chart = widget._chartWidget;
    var model = chart.model();
    var main = model.mainSeries();
    var bars = main.bars();
    if (!bars || typeof bars.firstIndex !== 'function' || typeof bars.lastIndex !== 'function') {
      return {success: false, error: 'mainSeries bars API unavailable'};
    }
    var first = bars.firstIndex();
    var last = bars.lastIndex();
    var out = [];
    for (var i = first; i <= last; i++) {
      var v = bars.valueAt(i);
      if (!v) continue;
      out.push({
        index: i,
        time: v[0],
        open: v[1],
        high: v[2],
        low: v[3],
        close: v[4],
        volume: v[5] || 0
      });
    }
    return {
      success: true,
      symbol: main.symbol ? main.symbol() : null,
      interval: main.interval ? main.interval() : null,
      first_index: first,
      last_index: last,
      size: bars.size ? bars.size() : out.length,
      bar_count: out.length,
      bars: out
    };
  } catch (e) {
    return {success: false, error: e.message, stack: e.stack};
  }
})()
`);

console.log(JSON.stringify(result, null, 2));
await disconnect();
