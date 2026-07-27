/*
 * Read-only charts for the local strategy status page.
 */

$(function(){
    const dataElement = document.getElementById("v5-ev-history-data");
    const chartElement = document.getElementById("v5-ev-history-chart");
    if(!dataElement || !chartElement || typeof Plotly === "undefined"){
        return;
    }
    let values;
    try{
        values = JSON.parse(dataElement.textContent);
    }catch(error){
        window.console&&console.error("Invalid V5 EV history payload", error);
        return;
    }
    if(
        !Array.isArray(values.timestamps)
        || !Array.isArray(values.expected_net_pct)
        || !values.timestamps.length
    ){
        return;
    }
    const acceptedX = [];
    const acceptedY = [];
    values.accepted.forEach((accepted, index) => {
        if(accepted){
            acceptedX.push(values.timestamps[index]);
            acceptedY.push(values.expected_net_pct[index]);
        }
    });
    const traces = [
        {
            x: values.timestamps,
            y: values.expected_net_pct,
            mode: "lines+markers",
            name: "EV V5",
            line: {color: "#17a2b8", width: 2},
            marker: {color: "#17a2b8", size: 4},
            hovertemplate: "%{x}<br>EV %{y:+.4f}%<extra></extra>"
        },
        {
            x: values.timestamps,
            y: values.timestamps.map(() => values.threshold_pct),
            mode: "lines",
            name: "Gate congelato",
            line: {color: "#ffc107", width: 2, dash: "dash"},
            hovertemplate: "Gate %{y:+.4f}%<extra></extra>"
        }
    ];
    if(acceptedX.length){
        traces.push({
            x: acceptedX,
            y: acceptedY,
            mode: "markers",
            name: "Ingresso accettato",
            marker: {
                color: "#198754",
                size: 10,
                symbol: "triangle-up"
            },
            hovertemplate: "%{x}<br>Ingresso · EV %{y:+.4f}%<extra></extra>"
        });
    }
    Plotly.newPlot(
        chartElement,
        traces,
        {
            title: {
                text: "Evoluzione del valore atteso V5 e distanza dal gate",
                font: {size: 16}
            },
            xaxis: {title: "Chiusura candela UTC"},
            yaxis: {
                title: "Valore atteso netto (%)",
                ticksuffix: "%"
            },
            shapes: [{
                type: "line",
                xref: "paper",
                x0: 0,
                x1: 1,
                y0: 0,
                y1: 0,
                line: {color: "rgba(128,128,128,0.6)", width: 1}
            }],
            legend: {orientation: "h", y: -0.25},
            margin: {l: 70, r: 20, t: 55, b: 80},
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            font: {color: getTextColor()}
        },
        {
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: [
                "select2d",
                "lasso2d",
                "toggleSpikelines"
            ]
        }
    );
});
