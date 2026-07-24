/*
 * Drakkar-Software OctoBot
 * Copyright (c) Drakkar-Software, All rights reserved.
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 3.0 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library.
 */

function get_symbol_price_graph(element_id, exchange_id, exchange_name, symbol, time_frame, display_orders, backtesting=false,
                                replace=false, should_retry=false, attempts=0,
                                data=undefined, success_callback=undefined, no_data_callback=undefined){
    if(isDefined(data)){
        create_or_update_candlestick_graph(element_id, data, symbol, exchange_name, time_frame, replace);
    }else{
        const backtesting_enabled = backtesting ? "backtesting" : "live";
        const ajax_url = "/dashboard/currency_price_graph_update/"+ exchange_id +"/" + symbol + "/"
            + time_frame + "/" + backtesting_enabled + "?display_orders=" + display_orders;
        $.ajax({
            url: ajax_url,
            type: "GET",
            dataType: "json",
            contentType: 'application/json',
            success: function(data, status){
                if(data !== null && "error" in data && data["error"].includes("no data for")){
                    if(isDefined(no_data_callback)) {
                        no_data_callback(element_id);
                    }
                }else if (!create_or_update_candlestick_graph(element_id, data, symbol, exchange_name, time_frame, replace)){
                    if (should_retry && attempts < max_attempts){
                        const marketsElement = $("#loadingMarketsDiv");
                        marketsElement.removeClass(disabled_item_class);
                        setTimeout(function(){
                            marketsElement.addClass(disabled_item_class);
                            get_symbol_price_graph(element_id, exchange_id, exchange_name, symbol, time_frame, display_orders, backtesting, replace, should_retry,attempts+1, data, success_callback);
                        }, 3000);
                    }
                }else{
                    const loadingSelector = $("div[name='loadingSpinner']");
                    if (loadingSelector.length) {
                        $.each(loadingSelector, function () {
                            $(this).addClass(disabled_item_class);
                        });
                    }
                    if(isDefined(success_callback)){
                        success_callback();
                    }
                }
            },
            error: function(result, status, error){
                window.console&&console.error(error, result, status);
                const loadingSelector = $("div[name='loadingSpinner']");
                if (loadingSelector.length) {
                    loadingSelector.addClass(hidden_class);
                }
                $(document.getElementById(element_id)).html(`<h7>Error when loading graph: ${error} [${result.responseText}]. More details in logs.</h7>`)
            }
        });
    }
}

function get_first_symbol_price_graph(element_id, in_backtesting_mode=false, callback=undefined, time_frame=undefined, display_orders=true) {
    const url = $("#first_symbol_graph").attr(update_url_attr);
    $.get(url,function(data) {
        if($.isEmptyObject(data)){
            // no exchange data available yet, retry soon, bot must be starting
            setTimeout(function(){
                get_first_symbol_price_graph(element_id, in_backtesting_mode, callback, time_frame, display_orders);
            }, 300);
        }else{
            if("time_frame" in data){
                let formatted_symbol = data["symbol"].replace(new RegExp("/","g"), "|");
                const fetched_time_frame = time_frame ? time_frame : data["time_frame"];
                get_symbol_price_graph(element_id, data["exchange_id"], data["exchange_name"], formatted_symbol,
                    fetched_time_frame, display_orders, in_backtesting_mode, false, true,
                    0, undefined, function () {
                        if(isDefined(callback)){
                            callback(data["exchange_id"], data["symbol"], data["time_frame"], element_id);
                        }
                    });
            }
        }
    });
}

function get_watched_symbol_price_graph(element, callback=undefined, no_data_callback=undefined, time_frame=undefined, display_orders=true) {
    const symbol = element.attr("symbol");
    let formatted_symbol = symbol.replace(new RegExp("/","g"), "|");
    const ajax_url = "/dashboard/watched_symbol/"+ formatted_symbol;
    $.get(ajax_url,function(data) {
        if("time_frame" in data){
            const fetched_time_frame = time_frame ? time_frame : data["time_frame"];
            let formatted_symbol = data["symbol"].replace(new RegExp("/","g"), "|");
            get_symbol_price_graph(element.attr("id"), data["exchange_id"], data["exchange_name"], formatted_symbol,
                fetched_time_frame, display_orders, false, false, true,
                0, undefined, function () {
                    if(isDefined(callback)){
                        callback(data["exchange_id"], data["symbol"], data["time_frame"], element.attr("id"));
                    }
                }, no_data_callback);
        }else if($.isEmptyObject(data)){
            // OctoBot is starting, try again
            const marketsElement = $("#loadingMarketsDiv");
            marketsElement.removeClass(disabled_item_class);
            setTimeout(function(){
                get_watched_symbol_price_graph(element, callback, no_data_callback, time_frame, display_orders);
            }, 1000);
        }
    });
}

const stop_color = getComputedStyle(document.body).getPropertyValue('--local-price-chart-stop-color');
const sell_color = getComputedStyle(document.body).getPropertyValue('--local-price-chart-sell-color');
const buy_color = getComputedStyle(document.body).getPropertyValue('--local-price-chart-buy-color');
const candle_sell_color = getComputedStyle(document.body).getPropertyValue('----local-price-chart-candle-sell-color');
const candle_buy_color = getComputedStyle(document.body).getPropertyValue('--local-price-chart-candle-buy-color');
const percentage_research_cache = {};
const percentage_causal_cache = {};
const percentage_probability_cache = {};
const percentage_long_hypothesis_cache = {};
const percentage_long_hypothesis_h2_cache = {};
const percentage_long_h1_style = {
    pathColor: "#20c997",
    longEntryColor: "#20c997",
    shortEntryColor: "#dc3545",
    longEntrySymbol: "diamond",
    shortEntrySymbol: "diamond",
    activationColor: "#ffc107",
    exitColor: "#9c27b0",
    annotationName: "percentage-long-hypothesis-h1",
    annotationX: 0.01,
    annotationAnchor: "left",
    evidenceText: "validazione riutilizzata: 87 casi · successo 36,8% (base 39,2%)"
};
const percentage_long_h2_style = {
    pathColor: "#007bff",
    longEntryColor: "#007bff",
    shortEntryColor: "#dc3545",
    longEntrySymbol: "triangle-up",
    shortEntrySymbol: "triangle-down",
    activationColor: "#fd7e14",
    exitColor: "#e83e8c",
    annotationName: "percentage-long-hypothesis-h2",
    annotationX: 0.99,
    annotationAnchor: "right",
    evidenceText: "KuCoin riutilizzato: 35 trade L/S · WR 60,0% · PF 2,00 (non validato)"
};

function create_candlesticks(candles){
    const data_time = candles["time"];
    const data_close = candles["close"];
    const data_high = candles["high"];
    const data_low = candles["low"];
    const data_open = candles["open"];

    return {
      x: data_time,
      close: data_close,
      decreasing: {line: {color: candle_sell_color}},
      high: data_high,
      increasing: {line: {color: candle_buy_color}},
      line: {color: 'rgba(31,119,180,1)'},
      low: data_low,
      open: data_open,
      type: 'candlestick',
      name: 'Prices',
      xaxis: 'x',
      yaxis: 'y2'
    };
}

function create_volume(candles){

    const data_time = candles["time"];
    const data_close = candles["close"];
    const data_volume = candles["vol"];
    
    const colors = [];
    $.each(data_close, function (i, value) {
        if(i !== 0) {
            if (value > data_close[i - 1]) {
                colors.push(buy_color);
            }else{
                colors.push(sell_color);
            }
        }
        else{
            colors.push(sell_color);
        }

    });

    return {
          x: data_time,
          y: data_volume,
          marker: {
              color: colors
          },
          type: 'bar',
          name: 'Volume',
          xaxis: 'x',
          yaxis: 'y1'
    };
}

function create_trades(trades, trader){

    if (isDefined(trades) && isDefined(trades["time"]) && trades["time"].length > 0) {
        const data_time = trades["time"];
        const data_price = trades["price"];
        const data_trade_description = trades["trade_description"];
        const data_order_side = trades["order_side"];

        const marker_size = 16;
        const marker_opacity =  0.9;
        const border_line_color = getTextColor();
        const colors = [];
        $.each(data_order_side, function (index, value) {
            colors.push(_getOrderColor(trades["trade_description"][index], value));
        });

        const line_with = isDarkTheme() ? 1 : 0.2;

        return {
            x: data_time,
            y: data_price,
            mode: 'markers',
            name: "",
            text: data_trade_description,
            hovertemplate: `%{text}<br>%{x}`,
            marker: {
                color: colors,
                size: marker_size,
                opacity: marker_opacity,
                line: {
                    width: line_with,
					color: border_line_color
                }
            },
            xaxis: 'x',
            yaxis: 'y2'
        }
    }else{
        return {}
    }
}

const _getOrderColor = (orderDesc, side) => {
    if(orderDesc.includes("STOP")){
        return stop_color;
    }
    return side === "sell" ? sell_color : buy_color
}

function create_orders(orders, trader, firstTime, lastTime){
    const firstDate = new Date(`20${firstTime}`)
    if (isDefined(orders) && isDefined(orders.time) && orders.time.length > 0) {
        return orders.time.map((x, index) => {
            return {
              x: [new Date(`20${x}`) >= firstDate ? x : firstTime, lastTime],
              y: [orders.price[index], orders.price[index]],
              mode: 'lines+markers',
              text: orders.description[index],
              hoverinfo: "text",
              line: {
                dash: 'dashdot',
                width: 2,
                color: _getOrderColor(orders.description[index], orders.order_side[index]),
              },
              marker: {
                  symbol: "star-diamond",
              },
              xaxis: 'x',
              yaxis: 'y2'
            }
        });
    }else{
        return []
    }
}

function update_trades(trades, trader_name, reference_trades){
    if(isDefined(reference_trades) && isDefined(reference_trades.y)){
        if(isDefined(trades.time) && trades.time.length){
            const new_trades = create_trades(trades, trader_name);
            if(new_trades.mode){
                for(let i=0; i<new_trades.x.length; i++){
                    reference_trades.x.push(new_trades.x[i]);
                    reference_trades.y.push(new_trades.y[i]);
                    reference_trades.text.push(new_trades.text[i]);
                    reference_trades.marker.color.push(new_trades.marker.color[i]);
                }
            }
        }
    }else{
        reference_trades = create_trades(trades, trader_name)
    }
    return reference_trades;
}

function update_last_candle(to_update_candles, to_update_vols, new_candles, last_price_trace_index, last_candle_index){
    to_update_candles.open[last_price_trace_index] = new_candles["open"][last_candle_index];
    to_update_candles.high[last_price_trace_index] = new_candles["high"][last_candle_index];
    to_update_candles.low[last_price_trace_index] = new_candles["low"][last_candle_index];
    to_update_candles.close[last_price_trace_index] = new_candles["close"][last_candle_index];
    to_update_vols.y[last_price_trace_index] = new_candles["vol"][last_candle_index];
    const prev_vol_color = new_candles["close"][last_candle_index] >= new_candles["open"][last_candle_index] ?
        buy_color : sell_color;
    to_update_vols.marker.color[last_price_trace_index] = prev_vol_color;
}

function create_layout(graph_title){
    return {
        title: graph_title,
        dragmode: isMobileDisplay() ? false : 'zoom',
        margin: {
            r: 10,
            t: 25,
            b: 40,
            l: 60
        },
        showlegend: false,
        xaxis: {
            autorange: true,
            domain: [0, 1],
            title: 'Date',
            type: 'date',
            rangeslider: {
                visible: false,
            }
        },
        yaxis1: {
            domain: [0, 0.2],
            title: 'Volume',
            autorange: true,
            showgrid: false,
            showticklabels: false
        },
        yaxis2: {
            domain: [0.2, 1],
            autorange: true,
            title: 'Price',
            gridcolor: `rgba(${getTextColorRGB()}, 0.2)`,
        },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: {
            color: getTextColor(),
        }
    };
}

function push_new_candle(price_trace, volume_trace, candles, candle_index, last_candle_time){
    price_trace.x.push(last_candle_time);
    price_trace.open.push(candles["open"][candle_index]);
    price_trace.high.push(candles["high"][candle_index]);
    price_trace.low.push(candles["low"][candle_index]);
    price_trace.close.push(candles["close"][candle_index]);
    volume_trace.y.push(candles["vol"][candle_index]);
    const vol_color = candles["close"][candle_index] >= candles["open"][candle_index] ?
        buy_color : sell_color;
    volume_trace.marker.color.push(vol_color);
}

function _percentage_research_hover(trade, stage){
    const direction = trade.direction === "LONG" ? "Long" : "Short";
    const stage_labels = {
        entry: "Entrata teorica",
        activation: "Profit lock attivato",
        exit: "Uscita teorica"
    };
    return [
        `<b>${stage_labels[stage]} · ${direction}</b>`,
        `Rendimento lordo: ${trade.gross_return_pct.toFixed(2)}%`,
        `MFE: ${trade.maximum_favorable_excursion_pct.toFixed(2)}%`,
        `MAE: ${trade.maximum_adverse_excursion_pct.toFixed(2)}%`,
        `Uscita: ${trade.exit_reason}`,
        "Diagnostica retrospettiva: usa candele future"
    ].join("<br>");
}

function _percentage_marker_trace(x, y, text, name, symbol, color){
    return {
        x: x,
        y: y,
        text: text,
        mode: "markers",
        name: name,
        hovertemplate: "%{text}<extra></extra>",
        marker: {
            symbol: symbol,
            color: color,
            size: 12,
            opacity: 0.95,
            line: {
                color: getTextColor(),
                width: 1
            }
        },
        xaxis: "x",
        yaxis: "y2"
    };
}

function create_percentage_research_traces(research){
    if(!isDefined(research) || !Array.isArray(research.trades) || !research.trades.length){
        return [];
    }
    const long_line = {x: [], y: []};
    const short_line = {x: [], y: []};
    const entries = {
        LONG: {x: [], y: [], text: []},
        SHORT: {x: [], y: [], text: []}
    };
    const activations = {x: [], y: [], text: []};
    const exits = {x: [], y: [], text: [], color: []};

    research.trades.forEach((trade) => {
        const line = trade.direction === "LONG" ? long_line : short_line;
        line.x.push(
            trade.entry_time,
            trade.activation_time,
            trade.exit_time,
            null
        );
        line.y.push(
            trade.entry_price,
            trade.activation_price,
            trade.exit_price,
            null
        );
        entries[trade.direction].x.push(trade.entry_time);
        entries[trade.direction].y.push(trade.entry_price);
        entries[trade.direction].text.push(_percentage_research_hover(trade, "entry"));
        activations.x.push(trade.activation_time);
        activations.y.push(trade.activation_price);
        activations.text.push(_percentage_research_hover(trade, "activation"));
        exits.x.push(trade.exit_time);
        exits.y.push(trade.exit_price);
        exits.text.push(_percentage_research_hover(trade, "exit"));
        exits.color.push(trade.direction === "LONG" ? "#198754" : "#dc3545");
    });

    const traces = [];
    [
        [long_line, "#198754", "Long hindsight path"],
        [short_line, "#dc3545", "Short hindsight path"]
    ].forEach(([line, color, name]) => {
        if(line.x.length){
            traces.push({
                x: line.x,
                y: line.y,
                mode: "lines",
                name: name,
                hoverinfo: "skip",
                line: {
                    color: color,
                    width: 2,
                    dash: "dot"
                },
                xaxis: "x",
                yaxis: "y2"
            });
        }
    });
    if(entries.LONG.x.length){
        traces.push(_percentage_marker_trace(
            entries.LONG.x,
            entries.LONG.y,
            entries.LONG.text,
            "Long entry",
            "triangle-up",
            "#198754"
        ));
    }
    if(entries.SHORT.x.length){
        traces.push(_percentage_marker_trace(
            entries.SHORT.x,
            entries.SHORT.y,
            entries.SHORT.text,
            "Short entry",
            "triangle-down",
            "#dc3545"
        ));
    }
    traces.push(_percentage_marker_trace(
        activations.x,
        activations.y,
        activations.text,
        "Profit lock activation",
        "diamond",
        "#ffc107"
    ));
    const exit_trace = _percentage_marker_trace(
        exits.x,
        exits.y,
        exits.text,
        "Hindsight exit",
        "circle",
        exits.color
    );
    traces.push(exit_trace);
    return traces;
}

function update_percentage_research_annotation(layout, research, enabled){
    const annotations = isDefined(layout.annotations) ? layout.annotations : [];
    layout.annotations = annotations.filter(
        (annotation) => annotation.name !== "percentage-research"
    );
    if(!enabled || !isDefined(research) || !isDefined(research.summary)){
        return;
    }
    const summary = research.summary;
    const config = research.config;
    layout.annotations.push({
        name: "percentage-research",
        xref: "paper",
        yref: "paper",
        x: 0.01,
        y: 0.99,
        xanchor: "left",
        yanchor: "top",
        showarrow: false,
        align: "left",
        bordercolor: "rgba(255, 193, 7, 0.85)",
        borderwidth: 1,
        borderpad: 5,
        bgcolor: "rgba(20, 20, 20, 0.78)",
        font: {
            color: "#ffffff",
            size: 11
        },
        text: (
            `<b>Mappa % retrospettiva — non è un segnale</b><br>` +
            `lock +${config.minimum_profit_pct}% dopo +${config.activation_pct}%, ` +
            `stop ${config.initial_stop_pct}%, orizzonte ${config.horizon_candles} candele<br>` +
            `${summary.selected_non_overlapping_trades} trade selezionati · ` +
            `hit rate storico ${summary.historical_hit_rate_pct.toFixed(1)}% · ` +
            `massimo composto lordo ${summary.maximum_hindsight_compounded_gross_return_pct.toFixed(1)}%`
        )
    });
}

function _percentage_causal_hover(trade, stage){
    const direction = trade.direction === "LONG" ? "Long" : "Short";
    const features = trade.signal_features;
    const stage_labels = {
        entry: "Ingresso causale V1",
        activation: "Profit lock attivato",
        exit: "Uscita valutata"
    };
    return [
        `<b>${stage_labels[stage]} · ${direction}</b>`,
        `Netto stimato: ${trade.net_return_pct.toFixed(2)}%`,
        `Lordo: ${trade.gross_return_pct.toFixed(2)}%`,
        `ATR: ${(features.atr_pct * 100).toFixed(3)}%`,
        `EMA spread direzionale: ${(features.directional_ema_spread_pct * 100).toFixed(3)}%`,
        `EMA slope direzionale: ${(features.directional_ema_slope_pct * 100).toFixed(3)}%`,
        `Uscita: ${trade.exit_reason}`,
        "L'ingresso non usa il futuro; l'esito sì"
    ].join("<br>");
}

function create_percentage_causal_traces(causal){
    if(!isDefined(causal) || !Array.isArray(causal.trades) || !causal.trades.length){
        return [];
    }
    const paths = {x: [], y: []};
    const entries = {x: [], y: [], text: [], color: []};
    const activations = {x: [], y: [], text: []};
    const exits = {x: [], y: [], text: [], color: []};

    causal.trades.forEach((trade) => {
        paths.x.push(trade.entry_time);
        paths.y.push(trade.entry_price);
        if(trade.activation_time !== null){
            paths.x.push(trade.activation_time);
            paths.y.push(trade.activation_price);
            activations.x.push(trade.activation_time);
            activations.y.push(trade.activation_price);
            activations.text.push(_percentage_causal_hover(trade, "activation"));
        }
        paths.x.push(trade.exit_time, null);
        paths.y.push(trade.exit_price, null);
        entries.x.push(trade.entry_time);
        entries.y.push(trade.entry_price);
        entries.text.push(_percentage_causal_hover(trade, "entry"));
        entries.color.push(trade.direction === "LONG" ? "#00bcd4" : "#9c27b0");
        exits.x.push(trade.exit_time);
        exits.y.push(trade.exit_price);
        exits.text.push(_percentage_causal_hover(trade, "exit"));
        exits.color.push(trade.net_return_pct > 0 ? "#20c997" : "#ff6b6b");
    });

    const traces = [{
        x: paths.x,
        y: paths.y,
        mode: "lines",
        name: "Causal V1 evaluated path",
        hoverinfo: "skip",
        line: {
            color: "#00bcd4",
            width: 3
        },
        xaxis: "x",
        yaxis: "y2"
    }];
    traces.push(_percentage_marker_trace(
        entries.x,
        entries.y,
        entries.text,
        "Causal V1 entry",
        "star",
        entries.color
    ));
    if(activations.x.length){
        traces.push(_percentage_marker_trace(
            activations.x,
            activations.y,
            activations.text,
            "Causal V1 profit lock",
            "diamond-open",
            "#ffc107"
        ));
    }
    traces.push(_percentage_marker_trace(
        exits.x,
        exits.y,
        exits.text,
        "Causal V1 exit",
        "square",
        exits.color
    ));
    return traces;
}

function update_percentage_causal_annotation(layout, causal, enabled){
    const annotations = isDefined(layout.annotations) ? layout.annotations : [];
    layout.annotations = annotations.filter(
        (annotation) => annotation.name !== "percentage-causal"
    );
    if(!enabled || !isDefined(causal) || !isDefined(causal.chart_summary)){
        return;
    }
    const chart = causal.chart_summary;
    const test = causal.frozen_evidence.test_metrics;
    const rule = causal.rule;
    layout.annotations.push({
        name: "percentage-causal",
        xref: "paper",
        yref: "paper",
        x: 0.99,
        y: 0.99,
        xanchor: "right",
        yanchor: "top",
        showarrow: false,
        align: "left",
        bordercolor: "rgba(0, 188, 212, 0.9)",
        borderwidth: 1,
        borderpad: 5,
        bgcolor: "rgba(20, 20, 20, 0.82)",
        font: {
            color: "#ffffff",
            size: 11
        },
        text: (
            `<b>Candidata causale V1 — NON approvata</b><br>` +
            `ATR ≤ ${(rule.maximum_atr_pct * 100).toFixed(3)}% · ` +
            `EMA spread ≥ ${(rule.minimum_directional_ema_spread_pct * 100).toFixed(3)}% · ` +
            `slope ≥ ${(rule.minimum_directional_ema_slope_pct * 100).toFixed(3)}%<br>` +
            `test KuCoin: ${test.trades} trade · WR ${test.win_rate_pct.toFixed(1)}% · ` +
            `PF ${test.profit_factor.toFixed(2)} · netto ${test.compounded_net_return_pct.toFixed(2)}%<br>` +
            `grafico: ${chart.non_overlapping_trades} trade · ` +
            `netto ${chart.compounded_net_return_pct.toFixed(2)}% · ` +
            `${chart.trades_per_day.toFixed(2)}/giorno · gate FALLITO`
        )
    });
}

function create_percentage_probability_traces(probability){
    if(!isDefined(probability) || !Array.isArray(probability.points)){
        return [];
    }
    return ["LONG", "SHORT"].map((direction) => {
        const points = probability.points.filter((point) => point.direction === direction);
        return {
            x: points.map((point) => point.time),
            y: points.map((point) => point.price),
            text: points.map((point) =>
                `${direction} · probabilità calibrata ${point.probability_pct.toFixed(1)}%` +
                `<br>${point.trade_qualified ? "sopra" : "sotto"} soglia economica ` +
                `${probability.display_threshold_pct.toFixed(1)}%` +
                `<br>punto diagnostico, non ingresso autorizzato`
            ),
            hoverinfo: "text",
            mode: "markers",
            name: `${direction} probability`,
            marker: {
                symbol: direction === "LONG" ? "triangle-up" : "triangle-down",
                size: 9,
                color: direction === "LONG" ? "#17a2b8" : "#fd7e14",
                line: {color: "#212529", width: 0.7}
            },
            type: "scatter"
        };
    });
}

function update_percentage_probability_annotation(layout, probability, enabled){
    layout.annotations = (layout.annotations || []).filter(
        (annotation) => annotation.name !== "percentage-probability"
    );
    if(
        !enabled || !isDefined(probability) || !isDefined(probability.latest)
        || !isDefined(probability.test)
    ){
        return;
    }
    const selected = probability.test.above_display_threshold;
    const sourceText = isDefined(probability.data_source)
        ? `<br>${probability.data_source} · ultima ${probability.snapshot_last_candle}`
        : "";
    const selectedText = selected.examples
        ? `${selected.examples} esempi ≥ soglia, successo reale ${selected.observed_pct.toFixed(1)}%`
        : "nessun esempio fuori campione ≥ soglia";
    layout.annotations.push({
        name: "percentage-probability",
        x: 0.99,
        y: 1.01,
        xref: "paper",
        yref: "paper",
        xanchor: "right",
        yanchor: "top",
        showarrow: false,
        align: "left",
        bordercolor: "#17a2b8",
        borderwidth: 1,
        borderpad: 5,
        bgcolor: "rgba(20, 20, 20, 0.82)",
        font: {color: "#ffffff", size: 11},
        text: (
            `<b>Probabilità ${probability.time_frame} — ricerca, NON segnale</b><br>` +
            `ultima candela chiusa: LONG ${probability.latest.long_probability_pct.toFixed(1)}% · ` +
            `SHORT ${probability.latest.short_probability_pct.toFixed(1)}%<br>` +
            `soglia economica ${probability.display_threshold_pct.toFixed(1)}% · ` +
            `${selectedText}<br>` +
            `test KuCoin: ${probability.test.examples} esempi · ` +
            `base ${probability.test.base_rate_pct.toFixed(1)}% · ` +
            `Brier ${probability.test.brier_score.toFixed(3)}` +
            sourceText
        )
    });
}

function create_percentage_long_hypothesis_traces(hypothesis, style){
    if(!isDefined(hypothesis) || !Array.isArray(hypothesis.trades)){
        return [];
    }
    const paths = {x: [], y: [], text: []};
    const entries = {
        LONG: {x: [], y: [], text: []},
        SHORT: {x: [], y: [], text: []}
    };
    const activations = {x: [], y: [], text: []};
    const exits = {x: [], y: [], text: []};
    hypothesis.trades.forEach((trade, index) => {
        const direction = trade.direction;
        const label = `${direction} ${hypothesis.hypothesis} #${index + 1}`;
        const probability = trade.probability_pct.toFixed(1);
        entries[direction].x.push(trade.entry_time);
        entries[direction].y.push(trade.entry_price);
        entries[direction].text.push(
            `<b>${label} · ENTRATA</b><br>` +
            `prezzo ${trade.entry_price.toFixed(2)} · probabilità ${probability}%<br>` +
            `score ${trade.raw_score.toFixed(3)} · volume z ${trade.entry_volume_zscore.toFixed(2)}<br>` +
            `stop −1,0% · attivazione +1,2% · diagnostico`
        );
        const pathX = [trade.entry_time];
        const pathY = [trade.entry_price];
        if(isDefined(trade.activation_time) && trade.activation_time !== null){
            activations.x.push(trade.activation_time);
            activations.y.push(trade.activation_price);
            activations.text.push(
                `<b>${label} · PROTEZIONE ATTIVA</b><br>` +
                `raggiunto +1,2% · stop portato a +1,0%`
            );
            pathX.push(trade.activation_time);
            pathY.push(trade.activation_price);
        }
        if(trade.status === "closed"){
            exits.x.push(trade.exit_time);
            exits.y.push(trade.exit_price);
            exits.text.push(
                `<b>${label} · USCITA</b><br>` +
                `${trade.exit_reason} · lordo ${trade.gross_return_pct.toFixed(2)}% · ` +
                `netto ${trade.net_return_pct.toFixed(2)}%`
            );
            pathX.push(trade.exit_time);
            pathY.push(trade.exit_price);
        }
        paths.x.push(...pathX, null);
        paths.y.push(...pathY, null);
    });
    const traces = [{
        x: paths.x,
        y: paths.y,
        mode: "lines",
        name: `${hypothesis.hypothesis} percorso`,
        hoverinfo: "skip",
        line: {color: style.pathColor, width: 1.5, dash: "dot"},
        type: "scatter"
    }];
    ["LONG", "SHORT"].forEach((direction) => {
        if(entries[direction].x.length){
            const isLong = direction === "LONG";
            traces.push(_percentage_marker_trace(
                entries[direction].x,
                entries[direction].y,
                entries[direction].text,
                `${direction} ${hypothesis.hypothesis} entrata`,
                isLong ? style.longEntrySymbol : style.shortEntrySymbol,
                isLong ? style.longEntryColor : style.shortEntryColor
            ));
        }
    });
    if(activations.x.length){
        traces.push(_percentage_marker_trace(
            activations.x, activations.y, activations.text,
            `${hypothesis.hypothesis} protezione +1%`, "star", style.activationColor
        ));
    }
    if(exits.x.length){
        traces.push(_percentage_marker_trace(
            exits.x, exits.y, exits.text,
            `${hypothesis.hypothesis} uscita`, "x", style.exitColor
        ));
    }
    return traces;
}

function update_percentage_long_hypothesis_annotation(layout, hypothesis, enabled, style){
    layout.annotations = (layout.annotations || []).filter(
        (annotation) => annotation.name !== style.annotationName
    );
    if(!enabled || !isDefined(hypothesis) || !isDefined(hypothesis.summary)){
        return;
    }
    const summary = hypothesis.summary;
    const pf = summary.profit_factor === null
        ? "∞ (nessuna perdita)"
        : summary.profit_factor.toFixed(2);
    layout.annotations.push({
        name: style.annotationName,
        x: style.annotationX,
        y: 0.02,
        xref: "paper",
        yref: "paper",
        xanchor: style.annotationAnchor,
        yanchor: "bottom",
        showarrow: false,
        align: "left",
        bordercolor: style.longEntryColor,
        borderwidth: 1,
        borderpad: 5,
        bgcolor: "rgba(20, 20, 20, 0.84)",
        font: {color: "#ffffff", size: 11},
        text: (
            `<b>${hypothesis.alternating_directions ? "H2 LONG/SHORT alternati" : "LONG H1"} 15m — test visivo, NON strategia</b><br>` +
            `score ≥ ${hypothesis.score_threshold.toFixed(3)}` +
            (hypothesis.minimum_volume_zscore === null
                ? ""
                : ` · volume z ≥ ${hypothesis.minimum_volume_zscore.toFixed(1)}`) +
            `<br>` +
            `stop −1% · attiva a +1,2% · protegge +1% · max 24h<br>` +
            (hypothesis.alternating_directions
                ? `alternanza obbligatoria · ${summary.long_trades} LONG · ${summary.short_trades} SHORT<br>`
                : "") +
            `${summary.closed_trades} chiusi · ${summary.open_trades} aperti · ` +
            `WR ${summary.win_rate_pct.toFixed(1)}% · PF ${pf} · ` +
            `netto composto ${summary.compounded_net_return_pct.toFixed(2)}%<br>` +
            style.evidenceText
        )
    });
}

function create_or_update_candlestick_graph(element_id, symbol_price_data, symbol, exchange_name, time_frame, replace=false){
    if (symbol_price_data) {
        const candles = symbol_price_data["candles"];
        const trades = symbol_price_data["trades"];
        const orders = symbol_price_data["orders"];
        const isSimulated = symbol_price_data["simulated"]
        if(isDefined(symbol_price_data["percentage_research"])){
            percentage_research_cache[element_id] = symbol_price_data["percentage_research"];
        }
        if(isDefined(symbol_price_data["percentage_causal"])){
            percentage_causal_cache[element_id] = symbol_price_data["percentage_causal"];
        }
        if(isDefined(symbol_price_data["percentage_probability"])){
            percentage_probability_cache[element_id] = symbol_price_data["percentage_probability"];
        }
        if(isDefined(symbol_price_data["percentage_long_hypothesis"])){
            percentage_long_hypothesis_cache[element_id] = symbol_price_data["percentage_long_hypothesis"];
        }
        if(isDefined(symbol_price_data["percentage_long_hypothesis_h2"])){
            percentage_long_hypothesis_h2_cache[element_id] = symbol_price_data["percentage_long_hypothesis_h2"];
        }
        const percentage_research = percentage_research_cache[element_id];
        const percentage_causal = percentage_causal_cache[element_id];
        const percentage_probability = percentage_probability_cache[element_id];
        const percentage_long_hypothesis = percentage_long_hypothesis_cache[element_id];
        const percentage_long_hypothesis_h2 = percentage_long_hypothesis_h2_cache[element_id];
        const percentage_research_enabled = (
            typeof shouldDisplayPercentageResearch === "function"
            && shouldDisplayPercentageResearch()
        );
        const percentage_causal_enabled = (
            typeof shouldDisplayPercentageCausal === "function"
            && shouldDisplayPercentageCausal()
        );
        const percentage_probability_enabled = (
            typeof shouldDisplayPercentageProbability === "function"
            && shouldDisplayPercentageProbability()
        );
        const percentage_long_hypothesis_enabled = (
            typeof shouldDisplayPercentageLongHypothesis === "function"
            && shouldDisplayPercentageLongHypothesis()
        );
        const percentage_long_hypothesis_h2_enabled = (
            typeof shouldDisplayPercentageLongHypothesisH2 === "function"
            && shouldDisplayPercentageLongHypothesisH2()
        );

        let layout = undefined;

        let price_trace = undefined;
        let volume_trace = undefined;

        let real_trader_trades = undefined;
        let simulator_trades = undefined;

        let plotted_orders = undefined;

        const prev_data = document.getElementById(element_id);
        const prev_layout = prev_data.layout;

        if (prev_layout && !replace) {
            volume_trace = prev_data.data[0];
            price_trace = prev_data.data[1];
            real_trader_trades = prev_data.data[2];
            simulator_trades = prev_data.data[3];

            // keep layout
            layout = prev_layout;
            // update data revision to force graph update
            layout.datarevision = (layout.datarevision || 0) + 1;

            // trades
            real_trader_trades = isSimulated ? real_trader_trades : update_trades(trades, "Real trader", real_trader_trades);
            simulator_trades = isSimulated ? update_trades(trades, "Simulator", simulator_trades) : simulator_trades;

            // candles
            if(isDefined(candles) && isDefined(candles.time) && candles.time.length){
                const last_price_trace_index = price_trace.close.length - 1;
                const last_candle_index = candles["close"].length - 1;
                const last_candle_time = candles["time"][last_candle_index];

                if (last_candle_index > 0){
                    // Candle update with last candle being and in-construction candle
                    if (price_trace.x[last_price_trace_index] !== last_candle_time) {
                        update_last_candle(price_trace, volume_trace, candles, last_price_trace_index, last_candle_index - 1);
                        push_new_candle(price_trace, volume_trace, candles, last_candle_index, last_candle_time);
                    } else {
                        update_last_candle(price_trace, volume_trace, candles, last_price_trace_index, last_candle_index);
                    }
                } else if(price_trace.x[last_price_trace_index].indexOf(last_candle_time) === -1) {
                    // Candle update with only one candle but this candle is not displayed (no in-construction candle)
                    push_new_candle(price_trace, volume_trace, candles, last_candle_index, last_candle_time);
                }
            }
        }
        if(!isDefined(layout)){
            let graph_title = symbol;
            if (exchange_name !== "ExchangeSimulator") {
                graph_title = graph_title + " (" + exchange_name + ", time frame: " + time_frame + ")";
            }
            layout = create_layout(graph_title);
        }
        if(!isDefined(price_trace)){
            price_trace = create_candlesticks(candles);
        }
        if(!isDefined(volume_trace)){
            volume_trace = create_volume(candles);
        }
        if(!isDefined(real_trader_trades)){
            real_trader_trades = isSimulated ? [] : create_trades(trades, "Real trader");
        }
        if(!isDefined(simulator_trades)){
            simulator_trades = isSimulated ? create_trades(trades, "Simulator") : [];
        }
        const lastTime = price_trace.x[price_trace.x.length - 1];
        const firstTime = price_trace.x[0];
        plotted_orders = create_orders(orders, isSimulated ? "Simulator": "Real trader", firstTime, lastTime);
        const percentage_research_traces = percentage_research_enabled
            ? create_percentage_research_traces(percentage_research)
            : [];
        const percentage_causal_traces = percentage_causal_enabled
            ? create_percentage_causal_traces(percentage_causal)
            : [];
        const percentage_probability_traces = percentage_probability_enabled
            ? create_percentage_probability_traces(percentage_probability)
            : [];
        const percentage_long_hypothesis_traces = percentage_long_hypothesis_enabled
            ? create_percentage_long_hypothesis_traces(
                percentage_long_hypothesis,
                percentage_long_h1_style
            )
            : [];
        const percentage_long_hypothesis_h2_traces = percentage_long_hypothesis_h2_enabled
            ? create_percentage_long_hypothesis_traces(
                percentage_long_hypothesis_h2,
                percentage_long_h2_style
            )
            : [];
        update_percentage_research_annotation(
            layout,
            percentage_research,
            percentage_research_enabled
        );
        update_percentage_causal_annotation(
            layout,
            percentage_causal,
            percentage_causal_enabled
        );
        update_percentage_probability_annotation(
            layout,
            percentage_probability,
            percentage_probability_enabled
        );
        update_percentage_long_hypothesis_annotation(
            layout,
            percentage_long_hypothesis,
            percentage_long_hypothesis_enabled,
            percentage_long_h1_style
        );
        update_percentage_long_hypothesis_annotation(
            layout,
            percentage_long_hypothesis_h2,
            percentage_long_hypothesis_h2_enabled,
            percentage_long_h2_style
        );

        const data = [
            volume_trace,
            price_trace,
            real_trader_trades,
            simulator_trades,
            ...plotted_orders,
            ...percentage_research_traces,
            ...percentage_causal_traces,
            ...percentage_probability_traces,
            ...percentage_long_hypothesis_traces,
            ...percentage_long_hypothesis_h2_traces
        ];
        const plotlyConfig = {
            staticPlot: isMobileDisplay(),
            scrollZoom: false,
            modeBarButtonsToRemove: ["select2d", "lasso2d", "toggleSpikelines"],
            responsive: true,
            showEditInChartStudio: true,
            displaylogo: false // no logo to avoid 'rel="noopener noreferrer"' security issue (see https://webhint.io/docs/user-guide/hints/hint-disown-opener/)
        };
        if(replace){
            Plotly.newPlot(element_id, data, layout, plotlyConfig);
        }else{
            Plotly.react(element_id, data, layout, plotlyConfig);
        }
        return true;
    }else{
        return false
    }
}
