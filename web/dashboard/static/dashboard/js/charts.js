// Draws every chart on the page. The data, colours and labels come ready from the server.

const MONO = 'ui-monospace, Consolas, monospace';

// Chart defaults
Chart.defaults.font.family = '"Instrument Sans", sans-serif';
Chart.defaults.font.size = 12;
Chart.defaults.color = '#6f6f6f';

function drawChart(canvas, config) {
  const many = config.datasets.length > 1;
  return new Chart(canvas, {
    type: 'line',
    data: { labels: config.labels, datasets: config.datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      spanGaps: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        // Legend
        legend: {
          display: many, align: 'start',
          labels: {
            boxWidth: 8, boxHeight: 8, usePointStyle: true, pointStyle: 'rectRounded', padding: 16,
            filter: (item, data) => !data.datasets[item.datasetIndex].hideFromLegend,
            sort: (a, b) => a.datasetIndex - b.datasetIndex,
          },
        },
        // Tooltip
        tooltip: {
          backgroundColor: '#19191b', titleColor: '#ededed', bodyColor: '#a1a1a6', padding: 12, cornerRadius: 8, boxPadding: 4,
          bodyFont: { family: MONO },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: 'rgba(23,23,23,.14)' }, ticks: { maxRotation: 0, autoSkipPadding: 16, font: { family: MONO } } },
        y: {
          grid: { color: 'rgba(23,23,23,.06)' }, border: { display: false }, ticks: { font: { family: MONO } },
          title: { display: Boolean(config.yLabel), text: config.yLabel },
        },
      },
    },
  });
}

// Find and draw
document.querySelectorAll('canvas[data-chart]').forEach((canvas) => {
  const source = document.getElementById(canvas.dataset.chart);
  if (source) drawChart(canvas, JSON.parse(source.textContent));
});
