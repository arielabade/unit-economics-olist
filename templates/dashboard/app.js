/* ABADE · Unit economics dashboard — behaviour.
 *
 * The page is complete without this file: every number is in the HTML and
 * every chart has a table twin. This script adds:
 *   - the charts, drawn from the JSON embedded by dashboard.py, in the colours
 *     of the active theme. plotly.js is fetched only when the first chart nears
 *     the viewport; if it cannot load, the table twins open instead;
 *   - the theme switch, the month selector, table sorting and filtering, and
 *     the section highlight in the navigation.
 */
(function () {
  "use strict";

  const DATA = JSON.parse(document.getElementById("dashboard-data").textContent);
  const root = document.documentElement;
  const mobile = () => window.matchMedia("(max-width: 720px)").matches;
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ formatting (pt-BR) */
  const NBSP = " ", MINUS = "−";
  const nf0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sign = (v) => (v < 0 ? MINUS : "");
  const brl = (v) => (v == null ? "—" : sign(v) + "R$" + NBSP + nf0.format(Math.abs(v)));
  const brlShort = (v) => {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 1e6) return sign(v) + "R$" + NBSP + nf2.format(a / 1e6) + NBSP + "mi";
    if (a >= 1e3) return sign(v) + "R$" + NBSP + nf0.format(a / 1e3) + NBSP + "mil";
    return brl(v);
  };
  const pct = (v, signed) => {
    if (v == null) return "—";
    const r = Math.round(v * 100);
    if (r === 0) return "0%";                       // never "−0%"
    return (r < 0 ? MINUS : signed ? "+" : "") + nf0.format(Math.abs(r)) + "%";
  };
  const times = (v) => (v == null ? "—" : nf2.format(v) + "x");
  const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const MONTHS_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
    "outubro", "novembro", "dezembro"];
  const monthName = (m) => MONTHS[+m.slice(5) - 1] + "/" + m.slice(0, 4);
  const monthLong = (m) => MONTHS_LONG[+m.slice(5) - 1] + " de " + m.slice(0, 4);
  const toDate = (m) => m + "-15";
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const label = (c) => DATA.labels[c] || c;
  const months = DATA.months;
  const prevMonth = (m) => { const y = +m.slice(0, 4), n = +m.slice(5); return n === 1 ? (y - 1) + "-12" : y + "-" + String(n - 1).padStart(2, "0"); };

  /* ------------------------------------------------------------ theme tokens */
  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  const color = (channel) => css("--c-" + channel) || css("--c-unpaid");
  function tokens() {
    return {
      ink: css("--ink"), ink2: css("--ink-2"), ink3: css("--ink-3"), grid: css("--grid"), axis: css("--axis"),
      surface: css("--surface"), accent: css("--accent"), unpaid: css("--c-unpaid"), all: css("--c-all"),
      bad: css("--bad"), good: css("--good"),
    };
  }

  function baseLayout(t, extra) {
    const m = mobile();
    return Object.assign({
      margin: { l: 8, r: m ? 8 : 16, t: 8, b: 8 },
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Lato, Helvetica Neue, Arial, sans-serif", color: t.ink2, size: m ? 12 : 13 },
      separators: ",.",
      hoverlabel: { font: { family: "Lato, sans-serif", size: 13, color: t.ink }, bgcolor: t.surface, bordercolor: t.axis },
      legend: { orientation: "h", x: 0, y: -0.16, yanchor: "top", font: { size: m ? 13 : 12, color: t.ink2 },
        itemclick: "toggle", itemdoubleclick: "toggleothers" },
      showlegend: false, xaxis: axis(t), yaxis: axis(t), dragmode: false,
    }, extra || {});
  }
  function axis(t, extra) {
    return Object.assign({
      gridcolor: t.grid, gridwidth: 1, zeroline: false, linecolor: t.axis, tickcolor: t.axis,
      tickfont: { color: t.ink2 }, title: { font: { color: t.ink2, size: 12 } }, automargin: true, fixedrange: true,
    }, extra || {});
  }
  // Time axes end where the data ends (no empty October 2026 tick).
  const timeAxis = (t) => axis(t, { type: "date", tickformat: "%b\n%Y", dtick: mobile() ? "M6" : "M3", ticklabelmode: "period",
    showgrid: false, range: [months[0] + "-01", months[months.length - 1] + "-28"] });
  const brlTicks = (max) => {
    const step = max > 120000 ? 50000 : max > 40000 ? 20000 : 10000;
    const vals = [];
    for (let v = 0; v <= max * 1.05; v += step) vals.push(v);
    return { tickvals: vals, ticktext: vals.map((v) => (v === 0 ? "R$" + NBSP + "0" : "R$" + NBSP + nf0.format(v / 1000) + NBSP + "mil")) };
  };
  const config = { responsive: true, displayModeBar: false, scrollZoom: false, locale: "pt-BR" };
  const dotted = (t) => ({ color: t.ink3, width: 1, dash: "dot" });

  const rows = (channel) => DATA.monthly.filter((r) => r.channel === channel).sort((a, b) => (a.month < b.month ? -1 : 1));

  /* ------------------------------------------------------------ charts */
  const CHARTS = {
    spend(t) {
      const paid = rows("paid_total");
      const ev = DATA.events;
      const max = Math.max(...paid.map((r) => r.spend));
      return {
        data: [{ type: "bar", x: paid.map((r) => toDate(r.month)), y: paid.map((r) => r.spend),
          marker: { color: color("paid_total"), cornerradius: 3 },
          customdata: paid.map((r) => [monthName(r.month), ev[r.month] ? "<br>" + esc(ev[r.month]) : ""]),
          hovertemplate: "<b>%{customdata[0]}</b><br>Investimento: R$ %{y:,.0f}%{customdata[1]}<extra></extra>" }],
        layout: baseLayout(t, { bargap: 0.35, xaxis: timeAxis(t),
          yaxis: axis(t, Object.assign({ range: [0, max * 1.08] }, brlTicks(max))) }),
      };
    },

    customers(t) {
      const paid = rows("paid_total"), store = rows("all");
      const line = (r, name, c, width) => ({
        type: "scatter", mode: "lines", name, x: r.map((x) => toDate(x.month)), y: r.map((x) => x.new_customers),
        line: { color: c, width },
        customdata: r.map((x) => monthName(x.month)), hovertemplate: "<b>%{customdata}</b><br>" + name + ": %{y:,.0f}<extra></extra>",
      });
      return {
        data: [line(store, "Loja inteira", t.all, 2), line(paid, "Mídia paga", color("paid_total"), 2.5)],
        layout: baseLayout(t, { showlegend: true, xaxis: timeAxis(t), yaxis: axis(t, { rangemode: "tozero", tickformat: ",.0f" }) }),
      };
    },

    cac(t) {
      const data = DATA.series.filter((c) => c !== "paid_shopping").map((c) => {
        const r = rows(c).filter((x) => x.cac != null && x.new_customers > 0);
        return {
          type: "scatter", mode: "lines+markers", name: label(c), x: r.map((x) => toDate(x.month)), y: r.map((x) => x.cac),
          line: { color: color(c), width: c === "paid_total" ? 3 : 2 },
          marker: { color: r.map((x) => (x.small_sample ? t.surface : color(c))), size: r.map((x) => (x.small_sample ? 9 : 6)),
            line: { color: color(c), width: r.map((x) => (x.small_sample ? 2 : 0)) } },
          visible: ["paid_total", "paid_social", "paid_search_generic"].includes(c) ? true : "legendonly",
          customdata: r.map((x) => [monthName(x.month), x.new_customers, x.spend, x.small_sample ? "<br>amostra pequena" : ""]),
          hovertemplate: "<b>" + esc(label(c)) + "</b> · %{customdata[0]}<br>CAC: R$ %{y:,.0f}<br>%{customdata[1]:,.0f} clientes · R$ %{customdata[2]:,.0f}%{customdata[3]}<extra></extra>",
        };
      });
      return { data, layout: baseLayout(t, { showlegend: true, hovermode: "closest", xaxis: timeAxis(t),
        yaxis: axis(t, { tickprefix: "R$" + NBSP, tickformat: ",.0f", rangemode: "tozero" }),
        legend: Object.assign(baseLayout(t).legend, { y: -0.14 }) }) };
    },

    ltvcac(t, el) {
      const total = DATA.summary.find((r) => r.channel === "paid_total");
      const paid = DATA.summary.filter((r) => DATA.paid.includes(r.channel) && !r.small_sample).sort((a, b) => a.ltv_cac_ratio - b.ltv_cac_ratio);
      el.style.height = paid.length * 54 + 80 + "px";
      // The decision zone is 1x to 3x: the axis stops at 4x, and a bar beyond it is cut with an arrow and its true value.
      const cap = 4;
      const m = mobile();
      return {
        data: [{ type: "bar", orientation: "h", y: paid.map((r) => r.label), x: paid.map((r) => Math.min(r.ltv_cac_ratio, cap)),
          marker: { color: paid.map((r) => color(r.channel)), cornerradius: 4 }, width: 0.5,
          text: paid.map((r) => (r.ltv_cac_ratio > cap ? times(r.ltv_cac_ratio) + " →" : times(r.ltv_cac_ratio)) +
            (m ? "" : "  ·  " + pct(r.spend / total.spend) + " do investimento")),
          textposition: paid.map((r) => (r.ltv_cac_ratio > cap ? "inside" : "outside")), insidetextanchor: "end",
          cliponaxis: false, textfont: { color: t.ink, size: 12 }, insidetextfont: { color: "#FFFFFF", size: 12 },
          customdata: paid.map((r) => [r.ltv_cac_ratio, r.cac, r.ltv, pct(r.spend / total.spend)]),
          hovertemplate: "<b>%{y}</b><br>LTV/CAC: %{customdata[0]:.2f}x<br>CAC R$ %{customdata[1]:,.0f} · LTV R$ %{customdata[2]:,.0f}<br>%{customdata[3]} do investimento<extra></extra>" }],
        layout: baseLayout(t, {
          shapes: [1, 3].map((v) => ({ type: "line", layer: "below", xref: "x", yref: "paper", x0: v, x1: v, y0: 0, y1: 1, line: dotted(t) })),
          xaxis: axis(t, { range: [0, cap], tickvals: [0, 1, 2, 3, 4], ticktext: ["0", "1x<br>empata", "2x", "3x<br>meta", "4x"], showgrid: false }),
          yaxis: axis(t, { showgrid: false, tickfont: { color: t.ink, size: 13 } }), margin: { l: 8, r: m ? 8 : 150, t: 8, b: 8 } }),
      };
    },

    retention(t, el) {
      const r = DATA.retention.filter((x) => x.channel !== "paid_total" && x.channel !== "all" && x.mature_customers >= 100)
        .sort((a, b) => a.repeat_rate_in_horizon - b.repeat_rate_in_horizon);
      const store = DATA.retention.find((x) => x.channel === "all");
      el.style.height = r.length * 30 + 80 + "px";
      return {
        data: [{ type: "scatter", mode: "markers+text", y: r.map((x) => x.label), x: r.map((x) => x.repeat_rate_in_horizon),
          text: r.map((x) => pct(x.repeat_rate_in_horizon)), textposition: "middle right", textfont: { color: t.ink2, size: 12 },
          marker: { color: r.map((x) => (DATA.series.includes(x.channel) ? color(x.channel) : t.unpaid)), size: 11, line: { color: t.surface, width: 2 } },
          customdata: r.map((x) => [x.repeat_rate_90d, x.orders_per_customer_in_horizon, x.mature_customers]),
          hovertemplate: "<b>%{y}</b><br>Voltou em 12 meses: %{x:.0%}<br>Voltou em 90 dias: %{customdata[0]:.0%}<br>Pedidos por cliente em 12 meses: %{customdata[1]:.2f}<br>Base: %{customdata[2]:,.0f} clientes<extra></extra>" }],
        layout: baseLayout(t, {
          shapes: [{ type: "line", xref: "x", yref: "paper", x0: store.repeat_rate_in_horizon, x1: store.repeat_rate_in_horizon, y0: 0, y1: 1, line: dotted(t) }],
          annotations: [{ x: store.repeat_rate_in_horizon, y: 1, xref: "x", yref: "paper", yanchor: "bottom", text: "loja inteira " + pct(store.repeat_rate_in_horizon), showarrow: false, font: { size: 11, color: t.ink2 } }],
          xaxis: axis(t, { tickformat: ".0%", range: [0.45, 0.8], dtick: mobile() ? 0.1 : 0.05 }), yaxis: axis(t, { showgrid: false, tickfont: { color: t.ink, size: 12 } }),
          margin: { l: 8, r: 8, t: 26, b: 8 },
        }),
      };
    },

    waterfall(t) {
      // Floating bars (base + height): the cartesian bundle ships no waterfall trace.
      const p = DATA.pnl, k = 100 / p.revenue;
      const steps = [
        ["Venda", p.revenue, "total"], ["Produto", -p.product_cost], ["Frete", -p.freight_cost],
        mobile() ? ["Devoluções", -(p.refunds - p.restocked_cost)] : ["Devolu-<br>ções", -(p.refunds - p.restocked_cost)],
        mobile() ? ["Taxa pgto.*", -p.payment_fee] : ["Taxa de<br>pgto.*", -p.payment_fee],
        mobile() ? ["Embalagem*", -p.variable_order_cost] : ["Emba-<br>lagem*", -p.variable_order_cost],
        ["Margem", p.contribution_margin, "total"], ["Mídia", -p.spend], ["Sobra", p.margin_after_media, "total"],
      ];
      let level = 0;
      const bars = steps.map(([name, v, kind]) => {
        const value = v * k;
        if (kind === "total") { level = value; return { name, base: 0, h: value, kind: "total" }; }
        const bar = { name, base: level + value, h: -value, kind: "cost" };
        level += value;
        return bar;
      });
      return {
        data: [{ type: "bar", x: bars.map((b) => b.name), y: bars.map((b) => b.h), base: bars.map((b) => b.base), width: 0.55,
          marker: { color: bars.map((b) => (b.kind === "total" ? t.all : t.unpaid)), cornerradius: 3 },
          text: bars.map((b) => (b.kind === "cost" ? MINUS : "") + nf1.format(b.h)), textposition: "outside", cliponaxis: false,
          textfont: { color: t.ink, size: 12 },
          customdata: bars.map((b) => (b.kind === "cost" ? "custa R$ " : "fica R$ ") + nf1.format(b.h) + " de cada R$ 100"),
          hovertemplate: "%{customdata}<extra></extra>" }],
        layout: baseLayout(t, { bargap: 0.3,
          xaxis: axis(t, { showgrid: false, tickangle: mobile() ? -50 : 0, tickfont: { size: mobile() ? 11 : 12, color: t.ink } }),
          yaxis: axis(t, { range: [0, 110], dtick: 20, tickprefix: "R$" + NBSP }) }),
      };
    },

    ceiling(t, el) {
      const r = DATA.summary.filter((x) => DATA.paid.includes(x.channel) && !x.small_sample).sort((a, b) => b.cac - a.cac);
      el.style.height = r.length * 64 + 90 + "px";
      const y = r.map((x) => x.label);
      const over = (x) => x.cac - x.cac_ceiling_at_3x;
      const links = r.map((x) => ({ type: "line", xref: "x", yref: "y", x0: x.cac_ceiling_at_3x, x1: x.cac, y0: x.label, y1: x.label,
        line: { color: over(x) > 0 ? t.bad : t.good, width: 3 } }));
      const max = Math.max(...r.map((x) => Math.max(x.break_even_cac, x.cac)));
      return {
        data: [
          { type: "scatter", mode: "markers", name: "Teto para empatar", y, x: r.map((x) => x.break_even_cac),
            marker: { color: t.surface, symbol: "diamond", size: 10, opacity: 0.9, line: { color: t.ink3, width: 2 } },
            hovertemplate: "<b>%{y}</b><br>Teto para empatar: R$ %{x:,.0f}<extra></extra>" },
          { type: "scatter", mode: "markers", name: "Teto para 3x", y, x: r.map((x) => x.cac_ceiling_at_3x),
            marker: { color: t.surface, size: 13, line: { color: t.ink, width: 2.5 } },
            hovertemplate: "<b>%{y}</b><br>Teto para 3x: R$ %{x:,.0f}<extra></extra>" },
          { type: "scatter", mode: "markers+text", name: "CAC atual", y, x: r.map((x) => x.cac),
            marker: { color: t.ink, size: 13, line: { color: t.surface, width: 2 } },
            // The gap is written out, so over/under never rests on red and green alone.
            text: r.map((x) => brl(x.cac) + (mobile() ? "" : "  (" + (over(x) > 0 ? "+" + brl(over(x)) + " acima" : brl(-over(x)) + " abaixo") + " do teto)")),
            customdata: r.map((x) => (over(x) > 0 ? "+" + brl(over(x)) + " acima do teto de 3x" : brl(-over(x)) + " abaixo do teto de 3x")),
            textposition: "top center", textfont: { color: t.ink, size: 11 },
            hovertemplate: "<b>%{y}</b><br>CAC atual: R$ %{x:,.0f}<br>%{customdata}<extra></extra>" },
        ],
        layout: baseLayout(t, { showlegend: true, shapes: links,
          xaxis: axis(t, { range: [-max * 0.22, max * 1.12], tickangle: 0, tickvals: [0, 100, 200, 300, 400].filter((v) => v <= max * 1.12),
            ticktext: [0, 100, 200, 300, 400].filter((v) => v <= max * 1.12).map((v) => (mobile() ? String(v) : "R$" + NBSP + v)),
            title: mobile() ? { text: "R$ por cliente", font: { size: 11, color: t.ink2 } } : undefined, zeroline: false }),
          yaxis: axis(t, { showgrid: false, tickfont: { color: t.ink, size: 12 } }),
          legend: Object.assign(baseLayout(t).legend, { y: -0.1 }) }),
      };
    },

    tornado(t, el) {
      // The four cost estimates move the answer by a few hundredths each: one row says so.
      const all = DATA.sensitivity.slice();
      const costs = all.filter((r) => /^(payment|variable)/.test(r.premise));
      const others = all.filter((r) => !/^(payment|variable)/.test(r.premise));
      const names = DATA.settingNames;
      const nm = (v) => names[v] || String(v).replace(".", ",");
      const s = others.map((r) => ({ label: r.label, detail: nm(r.low_setting) + " → " + nm(r.high_setting), low: r.low, high: r.high, base: r.base }))
        .concat([{ label: "Estimativas de custo", detail: "taxas de pagamento e embalagem, ±50%",
          low: Math.min(...costs.map((r) => r.low)), high: Math.max(...costs.map((r) => r.high)), base: costs[0].base }])
        .sort((a, b) => (a.high - a.low) - (b.high - b.low));
      const m = mobile();
      el.style.height = s.length * (m ? 96 : 76) + 80 + "px";
      const base = s[0].base;
      const ylabels = s.map((r, i) => String(i));
      return {
        data: [{ type: "bar", orientation: "h", y: ylabels, x: s.map((r) => Math.max(r.high - r.low, 0.01)), base: s.map((r) => r.low), width: 0.42,
          marker: { color: s.map((r, i) => (i === s.length - 1 ? t.ink : t.unpaid)), cornerradius: 4 },
          text: s.map((r) => times(r.low) + " a " + times(r.high)), textposition: "outside", cliponaxis: false, textfont: { color: t.ink, size: 12 },
          customdata: s.map((r) => r.label + " (" + r.detail + ")"),
          hovertemplate: "<b>%{customdata}</b><br>%{text}<extra></extra>" }],
        layout: baseLayout(t, {
          shapes: [{ type: "line", xref: "x", yref: "paper", x0: base, x1: base, y0: 0, y1: 1, line: { color: t.ink, width: 1.5 } }],
          // Premise names sit above their bars, so the plot keeps the full width on a phone.
          annotations: s.map((r, i) => ({ xref: "paper", x: 0, y: ylabels[i], yref: "y", xanchor: "left", yanchor: "bottom", yshift: m ? 16 : 14, showarrow: false, align: "left",
            bgcolor: t.surface, borderpad: 2,
            text: "<b>" + esc(r.label) + "</b>" + (m ? "<br>" : "  ") + "<span style='font-size:11px'>" + esc(r.detail) + "</span>", font: { size: 12, color: t.ink } }))
            .concat([{ x: base, y: 1, xref: "x", yref: "paper", yanchor: "bottom", text: "como medido: " + times(base), showarrow: false,
              bgcolor: t.surface, font: { size: 11, color: t.ink2 } }]),
          xaxis: axis(t, { ticksuffix: "x", range: [0.9, m ? 2.7 : 2.45], dtick: 0.5 }),
          yaxis: axis(t, { showgrid: false, showticklabels: false }), margin: { l: 8, r: 8, t: 30, b: 8 } }),
      };
    },

    horizon(t) {
      // Lines go light where fewer than 12 cohorts stand behind a point (the oldest, cheaper ones).
      const show = ["paid_total", "paid_social", "paid_search_generic", "performance_max", "paid_search_brand"];
      const data = [];
      show.forEach((c) => {
        const r = DATA.curve.filter((x) => x.channel === c).sort((a, b) => a.months - b.months);
        const solid = r.filter((x) => x.cohorts >= 12), thin = r.filter((x) => x.cohorts <= 12);
        const common = { type: "scatter", mode: "lines", legendgroup: c, visible: c === "paid_search_brand" ? "legendonly" : true };
        const hover = (part) => ({ customdata: part.map((x) => [x.margin_per_customer, x.cac, x.cohorts]),
          hovertemplate: "<b>" + esc(label(c)) + "</b> · mês %{x}<br>LTV/CAC: %{y:.2f}x<br>Margem acumulada R$ %{customdata[0]:,.0f} · CAC R$ %{customdata[1]:,.0f}<br>%{customdata[2]} coortes<extra></extra>" });
        data.push(Object.assign({}, common, hover(solid), { name: label(c), x: solid.map((x) => x.months), y: solid.map((x) => x.ltv_cac),
          line: { color: color(c), width: c === "paid_total" ? 3.5 : 2 } }));
        data.push(Object.assign({}, common, hover(thin), { name: label(c), showlegend: false, x: thin.map((x) => x.months), y: thin.map((x) => x.ltv_cac),
          opacity: 0.35, line: { color: color(c), width: c === "paid_total" ? 3.5 : 2 } }));
      });
      const ref = [[1, "empata"], [3, "meta 3x"]];
      return { data, layout: baseLayout(t, { showlegend: true, hovermode: "closest",
        shapes: ref.map(([v]) => ({ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: v, y1: v, line: dotted(t) })),
        annotations: ref.map(([v, text]) => ({ x: 0, y: v, xref: "paper", yref: "y", text, showarrow: false, xanchor: "left", yanchor: "bottom", font: { size: 11, color: t.ink2 } })),
        xaxis: axis(t, { dtick: 3, range: [0.5, 24.5], showgrid: false, ticksuffix: "º" }),
        yaxis: axis(t, { ticksuffix: "x", range: [0, 3.3] }) }) };
    },
  };

  /* ------------------------------------------------------------ plotly, on demand */
  let plotlyState = window.Plotly ? "ready" : "idle";
  const waiting = [];
  function withPlotly(fn) {
    if (plotlyState === "ready") return fn();
    if (plotlyState === "failed") return;
    waiting.push(fn);
    if (plotlyState === "loading") return;
    plotlyState = "loading";
    const tag = document.createElement("script");
    tag.src = SCRIPT.dataset.plotly;
    tag.async = true;
    tag.onload = () => { plotlyState = "ready"; registerLocale(); waiting.splice(0).forEach((f) => f()); };
    tag.onerror = fail;
    document.head.appendChild(tag);
  }
  const SCRIPT = document.querySelector("script[data-plotly]");
  function fail() {
    // Without the chart library the page falls back to its tables.
    plotlyState = "failed";
    document.querySelectorAll(".chart").forEach((c) => { c.hidden = true; });
    document.querySelectorAll("details.data-twin").forEach((d) => { d.open = true; });
  }
  function registerLocale() {
    if (registerLocale.done) return;
    Plotly.register({ moduleType: "locale", name: "pt-BR", dictionary: {},
      format: { days: ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"],
        shortDays: ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"],
        months: MONTHS_LONG, shortMonths: MONTHS, date: "%d/%m/%Y", decimal: ",", thousands: "." } });
    registerLocale.done = true;
  }

  /* ------------------------------------------------------------ rendering */
  const rendered = new Set();
  function draw(el) {
    withPlotly(() => {
      const build = CHARTS[el.dataset.chart];
      if (!build) return;
      const spec = build(tokens(), el);
      if (rendered.has(el)) {
        Plotly.react(el, spec.data, spec.layout, config);
      } else {
        el.textContent = "";
        Plotly.newPlot(el, spec.data, spec.layout, config);
        rendered.add(el);
      }
    });
  }
  const charts = Array.from(document.querySelectorAll("[data-chart]"));
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { draw(e.target); io.unobserve(e.target); } });
    }, { rootMargin: "400px 0px" });
    charts.forEach((el) => io.observe(el));
  } else {
    charts.forEach(draw);
  }
  const redrawAll = () => rendered.forEach((el) => draw(el));
  let resizeTimer, lastMobile = mobile();
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (mobile() !== lastMobile) { lastMobile = mobile(); redrawAll(); } }, 200);
  });
  window.addEventListener("beforeprint", () => charts.forEach((el) => { if (!rendered.has(el)) draw(el); }));

  /* ------------------------------------------------------------ theme */
  const toggle = document.getElementById("theme-toggle");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : systemDark.matches);
  function syncToggle() { toggle.hidden = false; toggle.setAttribute("aria-pressed", String(isDark())); }
  toggle.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("ue-theme", root.dataset.theme); } catch (e) {}
    syncToggle(); redrawAll();
  });
  systemDark.addEventListener("change", () => { if (!root.dataset.theme) { syncToggle(); redrawAll(); } });
  syncToggle();

  /* ------------------------------------------------------------ month table */
  const select = document.getElementById("month-select");
  const status = document.getElementById("month-status");
  const order = ["all", "paid_total"].concat(DATA.paid, ["organic_search", "direct", "organic_social", "email", "referral", "whatsapp", "untracked"]);
  const swatch = (c) => {
    const key = DATA.series.includes(c) ? c : c === "all" ? "all" : "unpaid";
    return '<span class="swatch" style="--sw: var(--c-' + key + ')" aria-hidden="true"></span>';
  };
  const delta = (v, goodUp, small) => {
    if (v == null) return '<td class="num">—</td>';
    const r = Math.round(v * 100);
    const arrow = r > 0 ? "▲" : r < 0 ? "▼" : "■";
    let tone = "", word = "";
    if (goodUp != null && r !== 0 && !small) {
      const better = (r > 0) === goodUp;
      tone = better ? " up-good" : " up-bad";
      word = '<span class="sr-only"> (' + (better ? "melhor" : "pior") + ")</span>";
    }
    return '<td class="num delta' + tone + '"><span aria-hidden="true">' + arrow + "</span> " + pct(v, true) + word + "</td>";
  };
  function head(m) {
    const y = +m.slice(0, 4);
    const before = "vs " + monthName(prevMonth(m)), ly = "vs " + monthName((y - 1) + m.slice(4));
    const g = (n, c) => '<th scope="colgroup" colspan="' + c + '" class="num group">' + n + "</th>";
    const sub = (cols) => cols.map((c) => '<th scope="col" class="num">' + c + "</th>").join("");
    return '<thead><tr><th scope="col" rowspan="2">Canal</th>' + g("Investimento", 3) + g("Clientes novos", 3) + g("Margem", 2) + g("CAC", 2) +
      "</tr><tr>" + sub(["valor", before, ly]) + sub(["número", before, ly]) + sub(["valor", ly]) + sub(["valor", ly]) + "</tr></thead>";
  }
  function renderMonth(m) {
    const part = {};
    DATA.monthly.forEach((r) => { if (r.month === m) part[r.channel] = r; });
    const body = order.filter((c) => part[c]).map((c) => {
      const r = part[c];
      const total = c === "all" || c === "paid_total";
      const small = !!r.small_sample && !total;
      const tag = small ? ' <span class="tag" title="Poucos clientes: não leia como tendência">amostra pequena</span>' : "";
      const spend = r.spend == null ? '<span class="na">sem mídia</span>' : brl(r.spend);
      const cac = r.cac == null ? '<span class="na">indefinido</span>' : brl(r.cac);
      return "<tr" + (total ? ' class="total"' : "") + '><th scope="row">' + swatch(c) + esc(label(c)) + tag + "</th>" +
        '<td class="num">' + spend + "</td>" + delta(r.spend_mom, null) + delta(r.spend_yoy, null) +
        '<td class="num">' + nf0.format(r.new_customers) + "</td>" + delta(r.new_customers_mom, true, small) + delta(r.new_customers_yoy, true, small) +
        '<td class="num">' + brlShort(r.contribution_margin) + "</td>" + delta(r.margin_yoy, true, small) +
        '<td class="num">' + cac + "</td>" + delta(r.cac_yoy, false, small) + "</tr>";
    }).join("");
    document.getElementById("month-table").innerHTML = head(m) + "<tbody>" + body + "</tbody>";
    status.textContent = "Mostrando " + monthLong(m) + (DATA.events[m] ? ", mês com " + DATA.events[m] : "") + ".";
  }
  if (select) select.addEventListener("change", () => renderMonth(select.value));

  /* ------------------------------------------------------------ channel table: sort + filter */
  const table = document.getElementById("channel-table");
  const sortStatus = document.getElementById("sort-status");
  if (table) {
    const tbody = table.tBodies[0];
    table.querySelectorAll("thead button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const col = +btn.dataset.sortCol;
        // Text columns start A→Z, numbers start with the largest.
        const first = col === 0 ? "asc" : "desc";
        const dir = btn.dataset.dir ? (btn.dataset.dir === "desc" ? "asc" : "desc") : first;
        table.querySelectorAll("thead button").forEach((b) => { delete b.dataset.dir; b.closest("th").removeAttribute("aria-sort"); });
        btn.dataset.dir = dir;
        btn.closest("th").setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
        const key = (tr) => {
          const v = tr.cells[col].dataset.sort;
          if (col === 0) return v;
          return v === "" || v == null ? null : +v;
        };
        const body = Array.from(tbody.rows);
        const totals = body.filter((tr) => tr.dataset.group === "total");
        const rest = body.filter((tr) => tr.dataset.group !== "total").sort((a, b) => {
          const x = key(a), y = key(b);
          if (x === null && y === null) return 0;
          if (x === null) return 1;            // an undefined CAC always sinks: never ranked as best
          if (y === null) return -1;
          const c = col === 0 ? String(x).localeCompare(String(y), "pt-BR") : x - y;
          return dir === "asc" ? c : -c;
        });
        rest.concat(totals).forEach((tr) => tbody.appendChild(tr));
        sortStatus.textContent = "Tabela ordenada por " + btn.textContent.trim().replace("¹", "") + ", " + (dir === "asc" ? "crescente" : "decrescente") + ".";
      });
    });
    document.querySelectorAll(".segmented button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".segmented button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        const f = btn.dataset.filter;
        Array.from(tbody.rows).forEach((tr) => { tr.hidden = !(f === "all" || tr.dataset.group === f || tr.dataset.group === "total"); });
        sortStatus.textContent = "Mostrando " + btn.textContent.trim().toLowerCase() + ".";
      });
    });
  }

  /* ------------------------------------------------------------ navigation highlight */
  const links = Array.from(document.querySelectorAll(".toc a"));
  const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
  if ("IntersectionObserver" in window) {
    const spy = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        const a = byId.get(e.target.id);
        if (!a) return;
        links.forEach((x) => x.removeAttribute("aria-current"));
        a.setAttribute("aria-current", "location");
        const ol = a.closest("ol");   // keep the active item visible in the list, never scroll the page
        ol.scrollTo({ left: a.parentElement.offsetLeft - ol.clientWidth / 2 + a.clientWidth / 2, behavior: reducedMotion() ? "auto" : "smooth" });
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    document.querySelectorAll("main section[id]").forEach((s) => spy.observe(s));
  }
})();
