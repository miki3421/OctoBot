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

$(document).ready(function() {
    const createHistoricalPortfolioChart = (element_id, reference_market, update) => {
        const element = $(`#${element_id}`);
        if (element.data("v13-paper") === true) {
            const source = document.getElementById("v13-paper-history");
            const history = source ? JSON.parse(source.textContent).map((point) => ({
                time: typeof point.time === "string" ? Date.parse(point.time.length === 10 ? `${point.time}T00:00:00Z` : point.time) / 1000 : point.time,
                value: point.value
            })) : [];
            const height = isMobileDisplay()? 250 : isMediumDisplay() ? 450 : undefined;
            if (history.length) {
                const currentValue = history[history.length - 1].value;
                const xaxis = {type: 'date', title: 'Ora UTC'};
                if (history.length === 1) {
                    xaxis.range = [new Date((history[0].time - 3600) * 1000).toISOString(), new Date((history[0].time + 3600) * 1000).toISOString()];
                }
                const draw = update ? Plotly.react : Plotly.newPlot;
                draw(document.getElementById(element_id), [{
                    x: history.map(point => new Date(point.time * 1000).toISOString()),
                    y: history.map(point => point.value), type: 'scatter', mode: 'lines+markers',
                    name: 'Equity paper', line: {color: '#29b6f6'}, marker: {size: 7},
                    hovertemplate: '%{x}<br>%{y:.2f} USDT<extra></extra>'
                }], {title: `${element.data('v13-label')} · ${currentValue.toFixed(2)} ${reference_market}`,
                    height: height || 400, xaxis, yaxis: {title: 'Equity (USDT)'},
                    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: {color: 'white'},
                    hoverlabel: {bgcolor: '#172b42', bordercolor: '#4f6b87', font: {color: '#f4f7fb'}}
                }, {responsive: true, displaylogo: false});
                $(`#profitability_graph`).removeClass(hidden_class);
                $(`#no_profitability_graph`).addClass(hidden_class);
            }
            return;
        }
        const selectedTimeFrame = "1d"; // todo add timeframe selector
        const url = `${element.data("url")}${selectedTimeFrame}`;
        const success = (updated_data, update_url, dom_root_element, msg, status) => {
            const graphDiv = $(`#profitability_graph`);
            const defaultDiv = $(`#no_profitability_graph`);
            const height = isMobileDisplay()? 250 : isMediumDisplay() ? 450 : undefined;
            if(msg.length > 1){
                graphDiv.removeClass(hidden_class);
                defaultDiv.addClass(hidden_class);
                const current_value = msg[msg.length - 1].value;
                const title = `${current_value > 0 ? current_value : '-'} ${reference_market}`
                create_line_chart(document.getElementById(element_id), msg, title, 'white', update, height);
            }else{
                graphDiv.addClass(hidden_class);
                defaultDiv.removeClass(hidden_class);
            }
        }
        send_and_interpret_bot_update(null, url, null, success, generic_request_failure_callback, "GET");
    }

    const displayPortfolioHistory = (elementId, referenceMarket, update) => {
        createHistoricalPortfolioChart(elementId, referenceMarket, update);
    }

    const update_display = (update) => {
        const elementId = "portfolio_historyChart";
        const referenceMarket = $(`#${elementId}`).data("reference-market");
        displayPortfolioHistory(elementId, referenceMarket, update);
    }

    const start_periodic_refresh = () => {
        setInterval(function() {
            update_display(true, true);
        }, profitability_update_interval);
    }

    let firstLoad = true;
    update_display(false);
    if(firstLoad){
        start_periodic_refresh();
    }
});
