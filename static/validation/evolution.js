// Evolución del modelo: dos charts (KPI series + gap por bin) sobre
// CalibrationSnapshots históricos. Lee JSON embebido por el template
// (json_script) y construye dos instancias de Chart.js.
(() => {
    const kpiEl = document.getElementById("kpi-data");
    const gapEl = document.getElementById("gap-data");
    const kpiCanvas = document.getElementById("kpi-chart");
    const gapCanvas = document.getElementById("gap-chart");
    if (!kpiEl || !gapEl || !kpiCanvas || !gapCanvas || typeof Chart === "undefined") {
        return;
    }
    const kpiData = JSON.parse(kpiEl.textContent);
    const gapData = JSON.parse(gapEl.textContent);

    // Colores consistentes con custom.css value-positive/negative.
    const COLOR_POSITIVE = "#16a34a"; // mejora / subestimado
    const COLOR_NEGATIVE = "#dc2626"; // empeora / sobreconfiado
    const COLOR_MUTED = "var(--pico-muted-color)";

    const gridColor = "rgba(128,128,128,0.15)";

    // --- KPI chart: multi-line, eje X temporal, no apiladas ---
    const kpiMetrics = [
        {key: "log_loss_1x2", label: "Log Loss 1X2", color: "#dc2626"},
        {key: "brier_1x2", label: "Brier 1X2", color: "#f59e0b"},
        {key: "rps_1x2", label: "RPS 1X2", color: "#8b5cf6"},
        {key: "ae_total", label: "MAE λ total", color: "#0ea5e9", hidden: true},
        {
            key: "top_score_hit_ratio",
            label: "Top Score %",
            color: "#16a34a",
            hidden: true,
        },
    ];

    new Chart(kpiCanvas, {
        type: "line",
        data: {
            labels: kpiData.map((d) => d.label),
            datasets: kpiMetrics.map((m) => ({
                label: m.label,
                data: kpiData.map((d) => d[m.key]),
                borderColor: m.color,
                backgroundColor: m.color,
                pointRadius: 3,
                pointHoverRadius: 6,
                borderWidth: 2,
                tension: 0.25,
                hidden: !!m.hidden,
            })),
        },
        options: {
            responsive: true,
            plugins: {
                tooltip: { mode: "index", intersect: false },
                legend: { labels: { color: COLOR_MUTED } },
            },
            scales: {
                x: {
                    ticks: { color: COLOR_MUTED, maxRotation: 45 },
                    grid: { color: gridColor },
                },
                y: {
                    ticks: { color: COLOR_MUTED },
                    grid: { color: gridColor },
                    beginAtZero: false,
                },
            },
        },
    });

    // --- Gap chart: una línea por bin, eje X temporal, gap en [-1, 1] ---
    // Construye labels únicos (timestamps ISO de todos los snapshots)
    // y alinea cada dataset con nulls donde el bin no aparece.
    const gapLabels = [];
    const gapLabelSet = new Set();
    gapData.forEach((s) => s.data.forEach((p) => gapLabelSet.add(p.x)));
    Array.from(gapLabelSet)
        .sort()
        .forEach((x) => gapLabels.push(x));

    new Chart(gapCanvas, {
        type: "line",
        data: {
            labels: gapLabels,
            datasets: gapData.map((s) => {
                const lookup = {};
                s.data.forEach((p) => (lookup[p.x] = p.gap));
                return {
                    label: `Bin ${s.bin_label}`,
                    data: gapLabels.map((x) =>
                        Object.prototype.hasOwnProperty.call(lookup, x)
                            ? lookup[x]
                            : null
                    ),
                    borderColor: _interpColor(parseFloat(s.bin_label)),
                    backgroundColor: _interpColor(parseFloat(s.bin_label)),
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    tension: 0.2,
                    spanGaps: true,
                };
            }),
        },
        options: {
            responsive: true,
            plugins: {
                tooltip: { mode: "index", intersect: false },
                legend: { labels: { color: COLOR_MUTED } },
            },
            scales: {
                x: {
                    ticks: {
                        color: COLOR_MUTED,
                        maxRotation: 45,
                        autoSkip: true,
                        callback: function (value, index) {
                            const label = this.getLabelForValue(value);
                            if (!label) return "";
                            // ISO timestamp → solo Y-M-D H:M
                            return label.length > 16 ? label.slice(5, 16) : label;
                        },
                    },
                    grid: { color: gridColor },
                },
                y: {
                    suggestedMin: -0.3,
                    suggestedMax: 0.3,
                    ticks: {
                        color: COLOR_MUTED,
                        callback: (v) => (v >= 0 ? `+${v}` : `${v}`),
                    },
                    grid: { color: gridColor },
                },
            },
        },
    });

    // Colorea los bins: gap > 0 (sobreconfiado) → rojizo, gap < 0
    // (subestimado) → verdoso. Bajas probabilidades (bin 0.0–0.3)
    // tienden a tener gap>0 (el modelo over-predice derrotas ), altas
    // (0.7–0.9) gap<0 (under-predice victorias). La interpolación
    // simplifica la lectura.
    function _interpColor(binStart) {
        // binStart 0..1 → hue 0 (rojo) a 120 (verde).
        // Mapeamos binStart -> 1 - binStart para que bin=0 sea más rojo
        // (el modelo típicamente sobre-confía en bins bajos) y bin=1 más
        // verde. Visualmente intuitivo: lo que el medio muestra es
        // "bajo→rojo, alto→verde".
        const t = Math.max(0, Math.min(1, 1 - binStart));
        const hue = t * 120;
        return `hsl(${hue.toFixed(0)}, 70%, 45%)`;
    }
})();