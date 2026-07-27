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

$(document).ready(function () {
    const handleAnnouncementsHide = () => {
        $("button[data-role=\"hide-announcement\"]").click(async (event) => {
            const source = $(event.currentTarget);
            const url = source.data("url");
            await async_send_and_interpret_bot_update(undefined, url);
        })
    }

    function _refresh_profitability(socket) {
        socket.emit('profitability');
        waiting_profitability_update = false;
    }

    function handle_profitability(socket) {
        socket.on("profitability", function (data) {
            updateProfitabilityDisplay(
                data["bot_real_profitability"], data["bot_real_flat_profitability"],
                data["bot_simulated_profitability"], data["bot_simulated_flat_profitability"],
            );
            if (!waiting_profitability_update) {
                // re-schedule profitability refresh
                waiting_profitability_update = true;
                setTimeout(function () {
                    _refresh_profitability(socket);
                }, profitability_update_interval);
            }
        })
    }

    const updateProfitabilityDisplay = (
        bot_real_profitability, bot_real_flat_profitability,
        bot_simulated_profitability, bot_simulated_flat_profitability
    ) => {
        if(isDefined(bot_real_profitability)){
            displayProfitability(bot_real_profitability, bot_real_flat_profitability);
        }
        else if(isDefined(bot_simulated_profitability)){
            displayProfitability(bot_simulated_profitability, bot_simulated_flat_profitability);
        }
    }

    const displayProfitability = (profitabilityValue, flatValue) => {
        const displayedValue = parseFloat(profitabilityValue.toFixed(2));
        const badge = $("#profitability-badge");
        const flatValueSpan = $("#flat-profitability");
        const flatValueText = $("#flat-profitability-text");
        const displayValue = $("#profitability-value");
        badge.removeClass(hidden_class);
        flatValueSpan.removeClass(hidden_class);
        if(profitabilityValue < 0){
            displayValue.text(displayedValue);
            flatValueText.text(flatValue);
            badge.addClass("badge-warning");
            badge.removeClass("badge-success");
        } else {
            displayValue.text(`+${displayedValue}`);
            flatValueText.text(`+${flatValue}`);
            badge.removeClass("badge-warning");
            badge.addClass("badge-success");
        }
    }

    function get_in_backtesting_mode() {
        return $("#first_symbol_graph").attr("backtesting_mode") === "True";
    }

    function init_dashboard_websocket() {
        socket = get_websocket("/dashboard");
    }

    function get_version_upgrade() {
        const upgradeVersionAlertDiv = $("#upgradeVersion");
        if(upgradeVersionAlertDiv.length){
            $.get({
                url: upgradeVersionAlertDiv.attr(update_url_attr),
                dataType: "json",
                success: function (msg, status) {
                    if (msg) {
                        upgradeVersionAlertDiv.text(msg);
                        upgradeVersionAlertDiv.parent().parent().removeClass(disabled_item_class);
                    }
                }
            })
        }
    }

    const onGraphUpdate = (data) => {
        if (onGraphUpdateCallback !== undefined){
            onGraphUpdateCallback();
        }
        update_graph(data);
    }

    function handle_graph_update() {
        socket.on('candle_graph_update_data', function (data) {
            onGraphUpdate(data);
        });
        socket.on('new_data', function (data) {
            debounce(
                () => update_graph(data, false),
                500
            );
        });
        socket.on('error', function (data) {
            if ("missing exchange manager" === data) {
                socket.off("candle_graph_update_data");
                socket.off("new_data");
                socket.off("error");
                socket.off("profitability");
                $('#exchange-specific-data').load(document.URL + ' #exchange-specific-data', function (data) {
                    init_graphs();
                });
            }
        });
    }

    function _find_symbol_details(symbol, exchange_id) {
        let found_update_detail = undefined;
        update_details.forEach((update_detail) => {
            if (update_detail.symbol.replace(new RegExp("/","g"), "|")
                === symbol.replace(new RegExp("/","g"), "|")
                && update_detail.exchange_id === exchange_id) {
                found_update_detail = update_detail;
            }
        })
        return found_update_detail;
    }

    function update_graph(data, re_update = true) {
        const candle_data = data.data;
        let update_detail = undefined;
        if (isDefined(data.request)) {
            update_detail = data.request;
            // ensure candles are from the right timeframe
            const client_update_detail = _find_symbol_details(candle_data.symbol, candle_data.exchange_id);
            if(typeof client_update_detail !== "undefined"
                && update_detail.time_frame !== client_update_detail.time_frame){
                // wrong time frame: don't update and don't ask for more update
                return
            }
        } else {
            update_detail = _find_symbol_details(candle_data.symbol, candle_data.exchange_id);
        }
        if (isDefined(update_detail)) {
            get_symbol_price_graph(update_detail.elem_id, update_detail.exchange_id, "",
                update_detail.symbol, update_detail.time_frame, shouldDisplayOrders(), get_in_backtesting_mode(),
                false, true, 0, candle_data);
            if (re_update) {
                setTimeout(function () {
                    socket.emit("candle_graph_update", update_detail);
                }, price_graph_update_interval);
            }
        }
    }

    function init_updater(exchange_id, symbol, time_frame, elem_id) {
        if (!get_in_backtesting_mode()) {
            let update_detail = _find_symbol_details(symbol, exchange_id);
            if(typeof update_detail === "undefined"){
                update_detail = {};
                update_detail.exchange_id = exchange_id;
                update_detail.symbol = symbol;
                update_detail.time_frame = time_frame;
                update_detail.elem_id = elem_id;
                update_details.push(update_detail);
            }else{
                update_detail.time_frame = time_frame;
            }
            setTimeout(function () {
                    if (isDefined(socket)) {
                        socket.emit("candle_graph_update", update_detail);
                    }
                },
                3000);
        }
    }

    function enable_default_graph(time_frame) {
        $("#first_symbol_graph").removeClass(hidden_class);
        Plotly.purge("graph-symbol-price");
        $("#graph-symbol-price").empty();
        get_first_symbol_price_graph("graph-symbol-price", get_in_backtesting_mode(), init_updater, time_frame, shouldDisplayOrders());
    }

    function no_data_for_graph(element_id) {
        document.getElementById(element_id).parentElement.classList.add(hidden_class);
        if ($(".candle-graph").not(`.${hidden_class}`).length === 0) {
            // enable default graph if no watched symbol graph can be displayed
            enable_default_graph();
        }
    }

    function init_graphs() {
        update_details = [];
        updatePriceGraphs();
        handle_graph_update(socket);
        handle_profitability(socket);
    }

    const shouldDisplayOrders = () => {
        return $("#displayOrderToggle").is(":checked");
    }

    const updatePriceGraphs = () => {
        let useDefaultGraph = true;
        const time_frame = $("#timeFrameSelect").val();
        $(".watched-symbol-graph").each(function () {
            useDefaultGraph = false;
            const element = $(this);
            Plotly.purge(element.attr("id"));
            element.empty();
            const graphTimeFrame = element.data("fixed-time-frame") || time_frame;
            get_watched_symbol_price_graph(
                element,
                init_updater,
                no_data_for_graph,
                graphTimeFrame,
                shouldDisplayOrders()
            );
        });
        if (useDefaultGraph) {
            enable_default_graph(time_frame);
        }
    }

    const updateDisplayTimeFrame = (timeFrame) => {
        const url = $("#timeFrameSelect").data("update-url");
        const request = {
            time_frame: timeFrame,
        }
        send_and_interpret_bot_update(request, url, null, undefined, generic_request_failure_callback);
    }

    const updateDisplayOrders = (display_orders) => {
        const url = $("#displayOrderToggle").data("update-url");
        const request = {
            display_orders: display_orders,
        }
        send_and_interpret_bot_update(request, url, null, undefined, generic_request_failure_callback);
    }

    const chartSeriesToggleIds = [
        "displayPercentageLongHypothesisToggle",
        "displayPercentageLongHypothesisH2Toggle",
        "displayPerfectMapForecastV2Toggle",
        "displayPerfectMapSimulatedPathToggle",
        "displayPercentageProbabilityToggle",
        "displayPercentageCausalToggle",
        "displayPercentageResearchToggle",
    ];
    const chartSeriesStorageKey = "octobot.chart-series.v1";

    const restoreChartSeriesPreferences = () => {
        try {
            const saved = JSON.parse(localStorage.getItem(chartSeriesStorageKey));
            if (!saved || typeof saved !== "object") {
                return;
            }
            chartSeriesToggleIds.forEach((id) => {
                if (typeof saved[id] === "boolean") {
                    $(`#${id}`).prop("checked", saved[id]);
                }
            });
        } catch (error) {
            // Storage can be unavailable in hardened/private browser modes.
        }
    }

    const saveChartSeriesPreferences = () => {
        const values = {};
        chartSeriesToggleIds.forEach((id) => {
            values[id] = $(`#${id}`).is(":checked");
        });
        try {
            localStorage.setItem(chartSeriesStorageKey, JSON.stringify(values));
        } catch (error) {
            // The controls still work for the current page without storage.
        }
    }

    const updateChartSeriesContext = () => {
        const timeFrame = $("#timeFrameSelect").val();
        const probabilityControl = $("#displayPercentageProbabilityToggle")
            .closest(".custom-control");
        const forecastV2Control = $("#displayPerfectMapForecastV2Toggle")
            .closest(".custom-control");
        const simulatedPathControl = $("#displayPerfectMapSimulatedPathToggle")
            .closest(".custom-control");
        const longHypothesisControl = $("#displayPercentageLongHypothesisToggle")
            .closest(".custom-control");
        const longHypothesisH2Control = $("#displayPercentageLongHypothesisH2Toggle")
            .closest(".custom-control");
        const causalControl = $("#displayPercentageCausalToggle")
            .closest(".custom-control");
        probabilityControl.toggleClass(
            "text-muted",
            timeFrame !== "5m" && timeFrame !== "15m"
        );
        forecastV2Control.toggleClass("text-muted", timeFrame !== "15m");
        simulatedPathControl.toggleClass("text-muted", timeFrame !== "15m");
        longHypothesisControl.toggleClass("text-muted", timeFrame !== "15m");
        longHypothesisH2Control.toggleClass("text-muted", timeFrame !== "15m");
        causalControl.toggleClass("text-muted", timeFrame !== "1h");

        let help = "La mappa perfetta è retrospettiva e usa dati futuri.";
        if (timeFrame === "15m") {
            help = (
                "15m live: confronta LONG H1 con H2 LONG/SHORT anticipata, " +
                "la previsione V2, il path prezzo diretto 1h–8h con " +
                "skill contro prezzo flat e la mappa ideale. " +
                "H2 resta confermata dal volume e con direzione alternata. " +
                "I marker sono allineati alla chiusura della " +
                "candela e restano test visivi non approvati."
            );
        } else if (timeFrame === "5m") {
            help = (
                "5m: storico locale esteso con aggiornamento pubblico KuCoin " +
                "ogni minuto; feed di ricerca separato dall'operatività."
            );
        } else if (timeFrame === "1h") {
            help = (
                "1h: sono disponibili i segnali causali V1 non approvati. " +
                "La mappa perfetta è retrospettiva."
            );
        }
        $("#chart-series-help").text(
            `${help} Clicca una voce della legenda Plotly per una singola serie.`
        );
    }

    const registerConfigUpdates = () => {
        $("#timeFrameSelect").on("change", () => {
            updateDisplayTimeFrame($("#timeFrameSelect").val())
            updateChartSeriesContext();
            updatePriceGraphs();
        })
        $("#displayOrderToggle").on("change", () => {
            updateDisplayOrders(shouldDisplayOrders());
            updatePriceGraphs();
        })
        $("#displayPercentageResearchToggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
        $("#displayPercentageCausalToggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
        $("#displayPercentageProbabilityToggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
        $("#displayPerfectMapForecastV2Toggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
        $("#displayPerfectMapSimulatedPathToggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
        $("#displayPercentageLongHypothesisToggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
        $("#displayPercentageLongHypothesisH2Toggle").on("change", () => {
            saveChartSeriesPreferences();
            updatePriceGraphs();
        })
    }

    let update_details = [];
    let waiting_profitability_update = false;

    let socket = undefined;

    restoreChartSeriesPreferences();
    updateChartSeriesContext();
    get_version_upgrade();
    init_dashboard_websocket();
    init_graphs();
    registerConfigUpdates();
    handleAnnouncementsHide();
});


let onGraphUpdateCallback = undefined
function registerGraphUpdateCallback(callback) {
    onGraphUpdateCallback = callback
}

function shouldDisplayPercentageResearch() {
    const toggle = $("#displayPercentageResearchToggle");
    return toggle.length > 0 && toggle.is(":checked");
}

function shouldDisplayPercentageCausal() {
    const toggle = $("#displayPercentageCausalToggle");
    return toggle.length > 0 && toggle.is(":checked");
}

function shouldDisplayPercentageProbability() {
    const toggle = $("#displayPercentageProbabilityToggle");
    return toggle.length > 0 && toggle.is(":checked");
}

function shouldDisplayPerfectMapForecastV2() {
    const toggle = $("#displayPerfectMapForecastV2Toggle");
    return toggle.length > 0 && toggle.is(":checked");
}

function shouldDisplayPerfectMapSimulatedPath() {
    const toggle = $("#displayPerfectMapSimulatedPathToggle");
    return toggle.length > 0 && toggle.is(":checked");
}

function shouldDisplayPercentageLongHypothesis() {
    const toggle = $("#displayPercentageLongHypothesisToggle");
    return toggle.length > 0 && toggle.is(":checked");
}

function shouldDisplayPercentageLongHypothesisH2() {
    const toggle = $("#displayPercentageLongHypothesisH2Toggle");
    return toggle.length > 0 && toggle.is(":checked");
}
