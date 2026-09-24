/* 小批量标签拼版工具 —— 前端逻辑（原生 JS，无构建） */
"use strict";

const $ = (id) => document.getElementById(id);

let lastPlan = null;     // 最近一次 /api/layout 返回的拼版结果
let lastParams = null;   // 对应的请求参数
let currentPage = 1;
let activeCalibration = null;  // 已应用的校准参数（仅用于下载/打印）
let markDefaults = { x: [], y: [] };  // 测试页默认刻线设计坐标

/* ---------------- 标签行 ---------------- */

function addLabelRow(spec) {
  const data = spec || { name: "", width: 60, height: 30, count: 10, allow_rotate: false };
  const row = document.createElement("div");
  row.className = "label-row";
  row.innerHTML = `
    <input type="text" class="l-name" placeholder="标签名称" value="${escapeAttr(data.name)}" />
    <input type="number" class="l-w" value="${data.width}" step="0.5" min="0.1" title="宽 mm" />
    <input type="number" class="l-h" value="${data.height}" step="0.5" min="0.1" title="高 mm" />
    <input type="number" class="l-c" value="${data.count}" step="1" min="1" title="份数" />
    <label class="rot-cell" title="允许旋转 90°">
      <input type="checkbox" class="l-r" ${data.allow_rotate ? "checked" : ""} />旋转
    </label>
    <button type="button" class="del" title="删除">✕</button>
  `;
  row.querySelector(".del").addEventListener("click", () => row.remove());
  $("label-rows").appendChild(row);
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

/* ---------------- 首张纸占用区行 ---------------- */

function addZoneRow(zone) {
  const data = zone || { x: 20, y: 20, width: 80, height: 40 };
  const row = document.createElement("div");
  row.className = "zone-row";
  row.innerHTML = `
    <span class="z-idx"></span>
    <input type="number" class="z-x" value="${data.x}" step="0.5" title="左上角 X（距纸左）mm" />
    <input type="number" class="z-y" value="${data.y}" step="0.5" title="左上角 Y（距纸顶）mm" />
    <input type="number" class="z-w" value="${data.width}" step="0.5" min="0.1" title="占用区宽 mm" />
    <input type="number" class="z-h" value="${data.height}" step="0.5" min="0.1" title="占用区高 mm" />
    <button type="button" class="del" title="删除">✕</button>
  `;
  row.querySelector(".del").addEventListener("click", () => {
    row.remove();
    refreshZoneIndex();
  });
  $("zone-rows").appendChild(row);
  refreshZoneIndex();
}

function refreshZoneIndex() {
  document.querySelectorAll(".zone-row").forEach((row, i) => {
    row.querySelector(".z-idx").textContent = `#${i + 1}`;
  });
}

/* ---------------- 参数收集 ---------------- */

function num(id) {
  return parseFloat($(id).value);
}

function collectParams() {
  const labels = [...document.querySelectorAll(".label-row")].map((row) => ({
    name: row.querySelector(".l-name").value.trim(),
    width: parseFloat(row.querySelector(".l-w").value),
    height: parseFloat(row.querySelector(".l-h").value),
    count: parseInt(row.querySelector(".l-c").value, 10),
    allow_rotate: row.querySelector(".l-r").checked,
  }));
  const occupied_zones = [...document.querySelectorAll(".zone-row")].map((row) => ({
    x: parseFloat(row.querySelector(".z-x").value),
    y: parseFloat(row.querySelector(".z-y").value),
    width: parseFloat(row.querySelector(".z-w").value),
    height: parseFloat(row.querySelector(".z-h").value),
  }));
  return {
    page_width: num("page-width"),
    page_height: num("page-height"),
    margin_top: num("margin-top"),
    margin_right: num("margin-right"),
    margin_bottom: num("margin-bottom"),
    margin_left: num("margin-left"),
    gap_x: num("gap-x"),
    gap_y: num("gap-y"),
    labels,
    occupied_zones,
  };
}

function validateParams(p) {
  const bad = (msg) => { throw new Error(msg); };
  for (const [name, v] of [
    ["纸宽", p.page_width], ["纸高", p.page_height],
  ]) if (!(v > 0)) bad(`${name}必须为正数。`);
  for (const z of p.occupied_zones) {
    if ([z.x, z.y, z.width, z.height].some((v) => !Number.isFinite(v))) {
      bad("占用区的 X / Y / 宽 / 高必须全部填写为数字。");
    }
    if (z.x < 0 || z.y < 0) bad("占用区左上角 X / Y 不能为负数。");
    if (z.width <= 0 || z.height <= 0) bad("占用区宽、高必须为正数。");
    if (z.x + z.width > p.page_width + 1e-6) {
      bad(`占用区越界：X + 宽 = ${+(z.x + z.width).toFixed(2)}mm，超过纸张宽度 ${p.page_width}mm。`);
    }
    if (z.y + z.height > p.page_height + 1e-6) {
      bad(`占用区越界：Y + 高 = ${+(z.y + z.height).toFixed(2)}mm，超过纸张高度 ${p.page_height}mm。`);
    }
  }
}

async function fetchSvg(page, { showOccupied = false, calibration = null } = {}) {
  const body = {
    page,
    show_margins: $("show-margins").checked,
    show_annotations: $("show-annotations").checked,
    show_occupied: showOccupied,
    calibration: calibration || null,
    params: lastParams,
  };
  const resp = await fetch("/api/svg", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || "SVG 生成失败");
  return resp.text();
}

async function renderPage() {
  if (!lastPlan) return;
  // 预览显示灰色占用区（仅第一页有），与下载/打印的 SVG 坐标完全一致；
  // 预览永不应用校准补偿（calibration=null），坐标与 /api/layout 一致
  const svg = await fetchSvg(currentPage, { showOccupied: true });
  $("svg-host").innerHTML = svg;
  $("page-info").textContent = `${currentPage} / ${lastPlan.pages.length}`;
  $("prev-page").disabled = currentPage <= 1;
  $("next-page").disabled = currentPage >= lastPlan.pages.length;
}

/* ---------------- 结果汇总 ---------------- */

function renderSummary(plan) {
  const el = $("summary");
  el.classList.remove("empty");
  const allPlaced = plan.total_placed === plan.total_requested;
  const zoneInfo = plan.occupied_zones.length
    ? `，首张纸含 <strong>${plan.occupied_zones.length}</strong> 个占用区（灰色）`
    : "";
  let html = `<div class="totals">
      共 <strong>${plan.total_requested}</strong> 个标签，
      排入 <strong class="ok">${plan.total_placed}</strong> 个，
      使用 <strong>${plan.pages.length}</strong> 张纸${zoneInfo}
      ${allPlaced ? "（全部排入 ✔）" : `，<strong style="color:var(--danger)">${plan.total_requested - plan.total_placed} 个未排入</strong>`}
    </div>
    <table>
      <thead><tr>
        <th>标签</th><th>规格 (mm)</th><th>需求</th><th>排入</th><th>其中旋转</th><th>未排入</th>
      </tr></thead><tbody>`;
  for (const s of plan.summaries) {
    html += `<tr class="${s.unplaced > 0 ? "unplaced" : ""}">
      <td>${escapeHtml(s.name || `#${s.type_index + 1}`)}</td>
      <td>${s.width} × ${s.height}</td>
      <td>${s.requested}</td>
      <td>${s.placed}</td>
      <td>${s.rotated}</td>
      <td>${s.unplaced > 0 ? s.unplaced : "—"}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  if (plan.warnings.length) {
    html += `<div class="warn"><strong>提示：</strong><ul>${
      plan.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")
    }</ul></div>`;
  }
  el.innerHTML = html;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------------- 事件 ---------------- */

$("add-label").addEventListener("click", () => addLabelRow());
$("add-zone").addEventListener("click", () => addZoneRow());

$("preset").addEventListener("change", (e) => {
  if (!e.target.value) return;
  const [w, h] = e.target.value.split(",").map(parseFloat);
  $("page-width").value = w;
  $("page-height").value = h;
});

$("params-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  lastParams = collectParams();
  currentPage = 1;
  try {
    validateParams(lastParams);
    const resp = await fetch("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastParams),
    });
    if (!resp.ok) {
      const detail = (await resp.json()).detail;
      throw new Error(Array.isArray(detail)
        ? detail.map((d) => d.msg).join("；")
        : detail);
    }
    lastPlan = await resp.json();
    renderSummary(lastPlan);
    $("preview-wrap").hidden = false;
    await renderPage();
  } catch (err) {
    lastPlan = null;
    $("preview-wrap").hidden = true;
    $("summary").className = "summary";
    $("summary").innerHTML =
      `<div class="warn"><strong>参数错误：</strong>${escapeHtml(err.message)}</div>`;
  }
});

$("prev-page").addEventListener("click", async () => {
  if (currentPage > 1) { currentPage--; await renderPage(); }
});
$("next-page").addEventListener("click", async () => {
  if (lastPlan && currentPage < lastPlan.pages.length) {
    currentPage++; await renderPage();
  }
});

$("show-margins").addEventListener("change", renderPage);
$("show-annotations").addEventListener("change", renderPage);

function downloadBlob(text, filename, type) {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function exportCalibration() {
  // 仅在勾选“导出时应用校准补偿”且已应用校准时返回校准参数
  return $("apply-calib-export").checked && activeCalibration
    ? activeCalibration
    : null;
}

function alertExportError(err) {
  alert(`导出被阻止：${err.message}`);
}

$("download-svg").addEventListener("click", async () => {
  try {
    const svg = await fetchSvg(currentPage, { calibration: exportCalibration() });
    downloadBlob(svg, `labels-page-${currentPage}.svg`, "image/svg+xml");
  } catch (err) { alertExportError(err); }
});

$("download-all").addEventListener("click", async () => {
  const calib = exportCalibration();
  try {
    for (let p = 1; p <= lastPlan.pages.length; p++) {
      const svg = await fetchSvg(p, { calibration: calib });
      downloadBlob(svg, `labels-page-${p}.svg`, "image/svg+xml");
      await new Promise((r) => setTimeout(r, 150)); // 避免浏览器拦截批量下载
    }
  } catch (err) { alertExportError(err); }
});

$("print-all").addEventListener("click", async () => {
  const calib = exportCalibration();
  const svgs = [];
  try {
    for (let p = 1; p <= lastPlan.pages.length; p++) {
      svgs.push(await fetchSvg(p, { calibration: calib }));
    }
  } catch (err) { alertExportError(err); return; }
  const w = lastPlan.page_width, h = lastPlan.page_height;
  const win = window.open("", "_blank");
  if (!win) { alert("浏览器拦截了打印窗口，请允许弹窗后重试。"); return; }
  win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>打印标签</title>
    <style>
      @page { size: ${w}mm ${h}mm; margin: 0; }
      html,body { margin:0; padding:0; }
      .sheet { width:${w}mm; height:${h}mm; overflow:hidden; page-break-after:always; }
      .sheet:last-child { page-break-after:auto; }
      svg { display:block; width:${w}mm; height:${h}mm; }
    </style></head><body>
    ${svgs.map((s) => `<div class="sheet">${s}</div>`).join("")}
    </body></html>`);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 400);
});

/* ---------------- 打印位置校准 ---------------- */

function addCalibRow(axis, designed, measured) {
  const row = document.createElement("div");
  row.className = "calib-row";
  row.innerHTML = `
    <input type="number" class="c-des" step="0.1" title="刻线设计坐标 mm" value="${designed ?? ""}" placeholder="设计" />
    <input type="number" class="c-mea" step="0.1" min="0" title="纸上实测坐标 mm" value="${measured ?? ""}" placeholder="实测" />
    <button type="button" class="del" title="删除">✕</button>
  `;
  row.querySelector(".del").addEventListener("click", () => row.remove());
  $(`calib-${axis}-rows`).appendChild(row);
}

async function refreshMarkDefaults(preserveRows) {
  const pw = parseFloat($("page-width").value);
  const ph = parseFloat($("page-height").value);
  if (!(pw > 0) || !(ph > 0)) return;
  let data;
  try {
    const resp = await fetch("/api/calibration/marks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_width: pw, page_height: ph }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail);
    data = await resp.json();
  } catch (err) {
    return; // 纸张过小等情况：保留现有录入，不打扰用户
  }
  const prev = markDefaults;
  markDefaults = { x: data.x_designed, y: data.y_designed };

  for (const axis of ["x", "y"]) {
    const container = $(`calib-${axis}-rows`);
    const rows = [...container.querySelectorAll(".calib-row")];
    const defaults = markDefaults[axis];
    if (!rows.length) {
      // 首次进入：填入该纸张尺寸的默认刻线
      defaults.forEach((d) => addCalibRow(axis, d, ""));
      continue;
    }
    if (!preserveRows) continue;
    // 纸张尺寸变化：仅更新“仍是默认刻线且未填实测”的行（按序号对齐），
    // 用户手动改过设计坐标或已填实测的行原样保留
    rows.forEach((row, i) => {
      const newD = defaults[i];
      const oldD = prev[axis] ? prev[axis][i] : undefined;
      if (newD === undefined || oldD === undefined) return;
      const desEl = row.querySelector(".c-des");
      const meaEl = row.querySelector(".c-mea");
      if (Math.abs(parseFloat(desEl.value) - oldD) < 1e-6 && meaEl.value.trim() === "") {
        desEl.value = newD;
      }
    });
  }
}

function collectCalibration() {
  const readAxis = (axis) =>
    [...$(`calib-${axis}-rows`).querySelectorAll(".calib-row")]
      .map((row) => ({
        designed: parseFloat(row.querySelector(".c-des").value),
        measured: parseFloat(row.querySelector(".c-mea").value),
      }))
      .filter((p) => Number.isFinite(p.designed) && Number.isFinite(p.measured));
  return { x_points: readAxis("x"), y_points: readAxis("y") };
}

function renderCalibResult(ok, payload) {
  const el = $("calib-result");
  el.hidden = false;
  el.classList.toggle("error", !ok);
  if (!ok) {
    el.innerHTML = `<strong>校准未应用：</strong>${escapeHtml(payload)}`;
    return;
  }
  const row = (name, r) => `
    <tr>
      <td>${name}</td>
      <td>${r.used} 条</td>
      <td>${r.scale_percent.toFixed(3)}%</td>
      <td>${r.offset > 0 ? "+" : ""}${r.offset.toFixed(2)} mm</td>
    </tr>`;
  el.innerHTML = `
    <strong>校准已生效（仅下载 / 打印时补偿，预览与排版坐标不变）。</strong>
    <table>
      <thead><tr><th>方向</th><th>刻线</th><th>走纸比例 k</th><th>零位偏移 b</th></tr></thead>
      <tbody>${row("X（横向走纸）", payload.x)}${row("Y（纵向走纸）", payload.y)}</tbody>
    </table>
    <div class="fit-note">已检查全部 ${payload.page_count} 页：补偿后的标签轮廓与裁切线均在纸张内 ✔</div>`;
}

$("apply-calib").addEventListener("click", async () => {
  if (!lastParams) {
    renderCalibResult(false, "请先点击「生成拼版」，校准需要基于当前排版检查补偿是否超出纸张。");
    return;
  }
  const calibration = collectCalibration();
  if (!calibration.x_points.length && !calibration.y_points.length) {
    renderCalibResult(false, "请至少录入一个方向的刻线实测值。");
    return;
  }
  try {
    const resp = await fetch("/api/calibration/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params: lastParams, calibration }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "校准校验失败");
    activeCalibration = calibration;
    const cb = $("apply-calib-export");
    cb.disabled = false;
    cb.checked = true;
    renderCalibResult(true, data);
  } catch (err) {
    activeCalibration = null;
    const cb = $("apply-calib-export");
    cb.checked = false;
    renderCalibResult(false, err.message);
  }
});

$("clear-calib").addEventListener("click", () => {
  activeCalibration = null;
  const cb = $("apply-calib-export");
  cb.checked = false;
  cb.disabled = true;
  $("calib-result").hidden = true;
  $("calib-result").innerHTML = "";
  for (const axis of ["x", "y"]) {
    const container = $(`calib-${axis}-rows`);
    container.innerHTML = "";
    markDefaults[axis].forEach((d) => addCalibRow(axis, d, ""));
  }
});

document.querySelectorAll(".calib-add").forEach((btn) => {
  btn.addEventListener("click", () => addCalibRow(btn.dataset.axis, "", ""));
});

async function fetchTestPageSvg() {
  const pw = parseFloat($("page-width").value);
  const ph = parseFloat($("page-height").value);
  if (!(pw > 0) || !(ph > 0)) throw new Error("请先填写有效的纸张宽、高。");
  const resp = await fetch(
    `/api/calibration/test-page?width=${pw}&height=${ph}`
  );
  if (!resp.ok) throw new Error((await resp.json()).detail || "测试页生成失败");
  return { svg: await resp.text(), w: pw, h: ph };
}

function printSvgInWindow(svg, w, h, title) {
  const win = window.open("", "_blank");
  if (!win) throw new Error("浏览器拦截了打印窗口，请允许弹窗后重试。");
  win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>
    <style>
      @page { size: ${w}mm ${h}mm; margin: 0; }
      html,body { margin:0; padding:0; }
      .sheet { width:${w}mm; height:${h}mm; overflow:hidden; }
      svg { display:block; width:${w}mm; height:${h}mm; }
    </style></head><body><div class="sheet">${svg}</div></body></html>`);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 400);
}

$("print-calib-page").addEventListener("click", async () => {
  try {
    const { svg, w, h } = await fetchTestPageSvg();
    printSvgInWindow(svg, w, h, "校准测试页");
  } catch (err) { alert(err.message); }
});

$("download-calib-page").addEventListener("click", async () => {
  try {
    const { svg } = await fetchTestPageSvg();
    downloadBlob(svg, "calibration-test-page.svg", "image/svg+xml");
  } catch (err) { alert(err.message); }
});

/* ---------------- 初始数据 ---------------- */

addLabelRow({ name: "品名标签", width: 60, height: 30, count: 20, allow_rotate: true });
addLabelRow({ name: "箱贴", width: 100, height: 70, count: 6, allow_rotate: false });
addLabelRow({ name: "小标", width: 40, height: 20, count: 50, allow_rotate: true });

// 按当前纸张尺寸预填校准刻线设计坐标
refreshMarkDefaults();

// 纸张尺寸变化时刷新默认刻线；用户已录入的行（含实测值）原样保留
let markRefreshTimer = null;
for (const id of ["page-width", "page-height", "preset"]) {
  $(id).addEventListener("change", () => {
    clearTimeout(markRefreshTimer);
    markRefreshTimer = setTimeout(() => refreshMarkDefaults(true), 200);
  });
}
