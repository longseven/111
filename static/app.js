"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  selectedFile: null,
  parsed: null,
  lastResponse: null,
  compose: [],
};

// ---------- 工具 ----------
function toast(msg, ms = 3000) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function show(id) { $(id).classList.remove("hidden"); }

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// 转义后把换行变成 <br>，让选择题选项等按行显示
function escBr(s) {
  return esc(s).replace(/\n/g, "<br>");
}

function setBusy(btn, busy, label) {
  if (busy) {
    btn.disabled = true;
    btn.dataset.label = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span>' + (label || "处理中…");
  } else {
    btn.disabled = false;
    btn.textContent = btn.dataset.label || label;
  }
}

// 用 KaTeX 渲染元素内的 $...$ 公式；KaTeX 未加载时退回纯文本兜底
function typeset(el) {
  if (window.renderMathInElement) {
    try {
      renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true },
        ],
        throwOnError: false,
      });
      return;
    } catch (e) {
      /* 落到兜底 */
    }
  }
  el.innerHTML = degradeMath(el.innerHTML);
}

function degradeMath(html) {
  return html.replace(/\$\$?([^$]+?)\$\$?/g, (_, m) =>
    m
      .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, "($1)/($2)")
      .replace(/\\sqrt\s*\{([^{}]*)\}/g, "√($1)")
      .replace(/\\times/g, "×")
      .replace(/\\cdot/g, "·")
      .replace(/\\div/g, "÷")
      .replace(/\\le(?:q)?/g, "≤")
      .replace(/\\ge(?:q)?/g, "≥")
      .replace(/\\neq/g, "≠")
      .replace(/\\pm/g, "±")
      .replace(/\\sim/g, "~")
      .replace(/\\%/g, "%")
      .replace(/\\left|\\right/g, "")
      .replace(/[{}]/g, "")
      .replace(/\\[a-zA-Z]+/g, "")
      .trim()
  );
}

// ---------- 文件选择 ----------
const dropZone = $("dropZone");
const fileInput = $("fileInput");

$("browseBtn").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) selectFile(fileInput.files[0]);
});

["dragenter", "dragover"].forEach((ev) =>
  dropZone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropZone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
  })
);
dropZone.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
});

function selectFile(f) {
  state.selectedFile = f;
  $("fileName").textContent = "已选择：" + f.name;
  const preview = $("filePreview");
  if (state.previewUrl) {
    URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = null;
  }
  if (f.type.startsWith("image/")) {
    state.previewUrl = URL.createObjectURL(f);
    preview.innerHTML = `<img src="${state.previewUrl}" alt="已上传题目" />`;
    preview.classList.remove("hidden");
  } else {
    preview.innerHTML = `<div class="file-pdf">📄 ${esc(f.name)}（已上传）</div>`;
    preview.classList.remove("hidden");
  }
}

$("count").addEventListener("input", (e) => {
  $("countLabel").textContent = e.target.value;
});

function getConditions() {
  return {
    difficulty_change: $("difficultyChange").value,
    target_type: $("targetType").value,
    scenario_theme: $("scenarioTheme").value.trim(),
    extra_instructions: $("extraInstructions").value.trim(),
    change_mode: $("changeMode").value,
    count: Number($("count").value),
    allow_extension: $("allowExtension").checked,
    grade_hint: "",
  };
}

// ---------- 进度条 ----------
function showProgress() {
  const el = $("progress");
  el.querySelectorAll(".pstep").forEach((s) => (s.className = "pstep"));
  el.classList.remove("hidden");
}
function setStep(i, st) {
  const s = $("progress").querySelector(`.pstep[data-step="${i}"]`);
  if (s) s.className = "pstep " + st; // active | done | error
}
function markError() {
  const a = $("progress").querySelector(".pstep.active");
  if (a) a.className = "pstep error";
}
function hideProgress() {
  $("progress").classList.add("hidden");
}

const STEP_NAMES = ["识别原题", "改编生成", "不超纲校验", "答案校验", "数值验算"];
function showGenError(msg) {
  const el = $("genError");
  el.textContent = msg;
  el.classList.remove("hidden");
}
function clearGenError() {
  $("genError").classList.add("hidden");
}

async function postForm(url, form) {
  const res = await fetch(url, { method: "POST", body: form });
  if (res.status === 401) showAuth();
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) showAuth();
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

// 流式改编：POST /api/adapt_stream，逐块读取 SSE，onProgress(累计文本)，done 返回 variants
async function streamAdapt(parsed, conditions, onProgress) {
  const res = await fetch("/api/adapt_stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parsed, conditions }),
  });
  if (res.status === 401) {
    showAuth();
    const e = new Error("请先登录");
    e.fatal = true;
    throw e;
  }
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch (e) { /* 非 JSON */ }
    const e = new Error(msg);
    e.fatal = res.status === 429 || res.status === 400; // 配额/参数错不回退
    throw e;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let acc = "";
  let variants = null;
  let errored = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      let evt;
      try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
      if (evt.type === "delta") {
        acc += evt.text;
        onProgress(acc);
      } else if (evt.type === "done") {
        variants = evt.variants;
      } else if (evt.type === "error") {
        errored = evt.error;
      }
    }
  }
  if (errored) {
    const e = new Error(errored);
    e.fatal = true; // 后端生成错误，回退非流式多半也一样
    throw e;
  }
  if (!variants) throw new Error("流式结果不完整"); // 传输中断，可回退
  return variants;
}

// 从流式 JSON 中提取已完整的 stem 字段值，供边出边显
function extractStems(jsonText) {
  const out = [];
  const re = /"stem"\s*:\s*"((?:\\.|[^"\\])*)"/g;
  let m;
  while ((m = re.exec(jsonText))) {
    try { out.push(JSON.parse('"' + m[1] + '"')); } catch (e) { /* 尚不完整 */ }
  }
  return out;
}

// 仅对网络层瞬断（Failed to fetch / 服务重启）自动重试；HTTP 错误（4xx/5xx）不重试
async function postJSONRetry(url, body, tries = 3) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try {
      return await postJSON(url, body);
    } catch (e) {
      lastErr = e;
      if (!/failed to fetch|networkerror|load failed|请求失败 \(0\)/i.test(e.message)) throw e;
      await new Promise((r) => setTimeout(r, 800 * (i + 1)));
    }
  }
  throw lastErr;
}

// 并发限流执行：保持结果顺序，limit 个槽位轮转，单项异常由 fn 自行兜底
async function runLimited(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i], i);
    }
  }
  const workers = [];
  for (let k = 0; k < Math.min(limit, items.length); k++) workers.push(worker());
  await Promise.all(workers);
  return results;
}

// ---------- 一键生成（分三步显示进度） ----------
$("generateBtn").addEventListener("click", async () => {
  if (!state.selectedFile) {
    toast("请上传题目图片或文件");
    return;
  }
  if ($("paperMode").checked) {
    await generatePaper();
    return;
  }
  const btn = $("generateBtn");
  btn.disabled = true;
  clearGenError();
  $("paperStatus").classList.add("hidden");
  showProgress();
  let cur = 0;
  try {
    // ① 识别原题
    cur = 0;
    setStep(0, "active");
    const form = new FormData();
    form.append("file", state.selectedFile);
    const parsed = await postForm("/api/parse", form);
    setStep(0, "done");

    // ② 改编生成（流式：边写边显；流式不可用时回退普通生成）
    cur = 1;
    setStep(1, "active");
    const conditions = getConditions();
    const preview = $("streamPreview");
    preview.classList.remove("hidden");
    preview.innerHTML = '<div class="stream-head">✍️ 正在改编…</div>';
    let adaptVariants;
    try {
      adaptVariants = await streamAdapt(parsed, conditions, (acc) => {
        const stems = extractStems(acc);
        preview.innerHTML =
          `<div class="stream-head">✍️ 正在改编…（已生成 ${stems.length} 道 · ${acc.length} 字）</div>` +
          stems
            .map((s, i) => `<div class="stream-item"><b>新题 ${i + 1}</b>　${escBr(s)}</div>`)
            .join("");
      });
    } catch (streamErr) {
      if (streamErr.fatal) throw streamErr;
      preview.innerHTML = '<div class="stream-head">流式不可用，改用普通生成…</div>';
      const r = await postJSON("/api/adapt", { parsed, conditions });
      adaptVariants = r.variants;
    }
    preview.classList.add("hidden");
    const adaptRes = { variants: adaptVariants };
    setStep(1, "done");

    // ③④⑤ 不超纲校验 + 答案校验 +（可选）sympy 数值验算：互不依赖，并行执行以提速
    const useSympy = $("sympyVerify").checked;
    setStep(2, "active");
    setStep(3, "active");
    let scopeChecks = [];
    let answerChecks = [];
    let sympyChecks = [];
    const vErrs = [];
    const tasks = [
      postJSONRetry("/api/verify", { parsed, variants: adaptRes.variants })
        .then((r) => { scopeChecks = r.scope_checks; setStep(2, "done"); })
        .catch((e) => { setStep(2, "error"); vErrs.push("不超纲校验：" + e.message); }),
      postJSONRetry("/api/verify_answer", { variants: adaptRes.variants })
        .then((r) => { answerChecks = r.answer_checks; setStep(3, "done"); })
        .catch((e) => { setStep(3, "error"); vErrs.push("答案校验：" + e.message); }),
    ];
    if (useSympy) {
      $("progress").querySelector('.pstep[data-step="4"]').classList.remove("hidden");
      setStep(4, "active");
      tasks.push(
        postJSONRetry("/api/verify_sympy", { variants: adaptRes.variants })
          .then((r) => { sympyChecks = r.sympy_checks; setStep(4, "done"); })
          .catch((e) => { setStep(4, "error"); vErrs.push("数值验算：" + e.message); })
      );
    }
    await Promise.all(tasks);
    if (vErrs.length) {
      showGenError(vErrs.join("\n") + "\n（改编结果已照常显示，仅缺对应徽章，可稍后重试）");
    }

    state.mode = "single";
    state.parsed = parsed;
    state.lastResponse = { variants: adaptRes.variants };
    renderParsedSummary(parsed);
    renderResults({
      variants: adaptRes.variants,
      scope_checks: scopeChecks,
      answer_checks: answerChecks,
      sympy_checks: sympyChecks,
    });
    show("step-results");
    setTimeout(hideProgress, 700);
    $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    markError();
    $("streamPreview").classList.add("hidden");
    showGenError(`【${STEP_NAMES[cur]}】失败：${err.message}\n（详细报错见运行 ./run.sh 的终端窗口）`);
  } finally {
    btn.disabled = false;
  }
});

// ---------- 整卷模式：拆分 → 逐题改编 → 组卷 ----------
async function generatePaper() {
  const btn = $("generateBtn");
  btn.disabled = true;
  clearGenError();
  $("progress").classList.add("hidden");
  const status = $("paperStatus");
  status.classList.remove("hidden");
  status.textContent = "正在拆分试卷…";
  try {
    const form = new FormData();
    form.append("file", state.selectedFile);
    const split = await postForm("/api/split", form);
    const problems = split.problems || [];
    if (!problems.length) throw new Error("未能从试卷中识别出题目");

    const conditions = getConditions();
    // 多题并发改编：限并发避免压垮代理；单题失败不影响整卷，记为 failed 占位
    const PAPER_CONCURRENCY = 3;
    let done = 0;
    let failed = 0;
    status.textContent = `正在改编 0/${problems.length} 题…（并发处理中）`;
    const results = await runLimited(problems, PAPER_CONCURRENCY, async (text) => {
      try {
        const f = new FormData();
        f.append("text", text);
        const parsed = await postForm("/api/parse", f);
        const adaptRes = await postJSON("/api/adapt", { parsed, conditions });
        return { parsed, variants: adaptRes.variants };
      } catch (e) {
        failed++;
        return { parsed: { problem_text: text }, variants: [], error: e.message };
      } finally {
        done++;
        status.textContent = `正在改编 ${done}/${problems.length} 题…（并发处理中）`;
      }
    });
    const groups = results;
    const okCount = groups.length - failed;
    status.textContent =
      `完成：共 ${groups.length} 道题，成功 ${okCount} 题` +
      (failed ? `，失败 ${failed} 题（已保留原题占位，可单独重试）` : "") +
      "（整卷模式未做不超纲/答案校验）";
    state.mode = "paper";
    state.paperGroups = groups;
    renderPaper(groups);
    show("step-results");
    $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showGenError(`整卷改编失败：${err.message}\n（详细报错见运行 ./run.sh 的终端窗口）`);
  } finally {
    btn.disabled = false;
  }
}

function renderParsedSummary(p) {
  const kps = (p.knowledge_points || [])
    .map((k) => `<span class="tag">${esc(k)}</span>`).join("");
  $("parsedSummary").innerHTML = `
    <div class="kv"><b>识别原题</b>${escBr(p.problem_text)}</div>
    <div class="kv"><b>知识点</b>${kps}　<b>学段</b>${esc(p.grade_band)}　<b>难度</b>${esc(p.difficulty)}　<b>题型</b>${esc(p.problem_type)}</div>
  `;
  typeset($("parsedSummary"));
}

// ---------- 结果 ----------
let copyRegistry = [];

function variantCardHtml(v, displayIndex, opts = {}) {
  const { check, ans, sym, showBadges = true } = opts;
  const passed = check ? check.passed : true;
  let badge = "";
  if (showBadges) {
    if (!check) badge = '<span class="badge neutral">— 未校验</span>';
    else if (check.passed) badge = '<span class="badge ok">✓ 不超纲</span>';
    else badge = '<span class="badge bad">✗ 可能超纲</span>';
  }
  let ansBadge = "";
  if (showBadges && ans) {
    ansBadge = ans.correct
      ? '<span class="badge ok">✓ 答案已复核</span>'
      : '<span class="badge bad">✗ 答案存疑</span>';
  }
  // sympy 数值验算徽章：passed true/false/null（不可验算）
  let symBadge = "";
  if (showBadges && sym) {
    if (sym.passed === true) symBadge = '<span class="badge ok">✓ 数值已验算</span>';
    else if (sym.passed === false) symBadge = '<span class="badge bad">✗ 数值不符</span>';
    else symBadge = '<span class="badge neutral">— 数值未验算</span>';
  }
  const ansBlock = showBadges && ans && !ans.correct
    ? `<div class="field reason" style="background:#fbeae8;border-left-color:var(--bad)"><div class="label">答案存疑</div>独立复核正确答案应为：${escBr(ans.correct_answer)}<br>${esc(ans.reason)}</div>`
    : "";
  let symBlock = "";
  if (showBadges && sym && sym.passed === false) {
    symBlock = `<div class="field reason" style="background:#fbeae8;border-left-color:var(--bad)"><div class="label">sympy 验算不符</div>独立计算结果为：${escBr(sym.computed || "—")}<br>${esc(sym.note || "")}</div>`;
  } else if (showBadges && sym && sym.passed === null && sym.error) {
    symBlock = `<div class="field"><div class="label">数值验算</div>未能验算：${esc(sym.error)}</div>`;
  }
  const checkReason = showBadges && check
    ? `<div class="field"><div class="label">校验说明</div>${esc(check.reason)}</div>`
    : "";
  const kps = (v.knowledge_points || [])
    .map((k) => `<span class="tag">${esc(k)}</span>`).join("");
  const flagged = showBadges && !(passed && (!ans || ans.correct) && (!sym || sym.passed !== false));
  const cid = copyRegistry.push(v) - 1;
  return `
    <div class="variant ${flagged ? "flagged" : ""}">
      <h3>新题 ${displayIndex} ${badge} ${ansBadge} ${symBadge}</h3>
      <div class="field stem"><div class="label">题干</div>${escBr(v.stem)}</div>
      <div class="field"><div class="label">参考答案</div>${escBr(v.answer)}</div>
      ${ansBlock}
      ${symBlock}
      <div class="field"><div class="label">解析</div>${escBr(v.solution)}</div>
      <div class="field"><div class="label">知识点</div>${kps}　难度：${esc(v.difficulty)}</div>
      <div class="field reason"><div class="label">改编理由</div>${escBr(v.adaptation_reason)}</div>
      <div class="field"><div class="label">不超纲自检</div>${esc(v.within_scope_note)}</div>
      ${checkReason}
      <div class="card-ops">
        <button class="link" data-edit="${cid}">编辑</button>
        <button class="link" data-copy="${cid}">复制本题</button>
      </div>
    </div>`;
}

function attachCopyHandlers() {
  document.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", () => {
      const v = copyRegistry[Number(b.dataset.copy)];
      const txt = `${v.stem}\n\n答案：${v.answer}\n解析：${v.solution}`;
      navigator.clipboard.writeText(txt).then(() => toast("已复制到剪贴板"));
    })
  );
}

// ---------- 在线编辑 ----------
function attachEditHandlers() {
  document.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => openVariantEditor(b.dataset.edit))
  );
}

const _EDIT_FIELDS = [
  { f: "stem", label: "题干", rows: 3 },
  { f: "answer", label: "参考答案", rows: 2 },
  { f: "solution", label: "解析", rows: 3 },
  { f: "adaptation_reason", label: "改编理由", rows: 2 },
  { f: "within_scope_note", label: "不超纲自检", rows: 2 },
];

function openVariantEditor(cid) {
  const v = copyRegistry[Number(cid)];
  const btn = document.querySelector(`[data-edit="${cid}"]`);
  if (!btn) return;
  const card = btn.closest(".variant");
  const fieldsHtml = _EDIT_FIELDS
    .map(
      (cfg) =>
        `<label class="edit-field"><span>${cfg.label}</span><textarea data-f="${cfg.f}" rows="${cfg.rows}"></textarea></label>`
    )
    .join("");
  card.innerHTML = `
    <h3>编辑题目</h3>
    ${fieldsHtml}
    <label class="edit-field"><span>知识点（逗号分隔）</span><input type="text" data-f="kp" /></label>
    <label class="edit-field"><span>难度</span><input type="text" data-f="difficulty" /></label>
    <div class="edit-actions">
      <button class="primary" data-save>保存</button>
      <button class="link" data-cancel>取消</button>
    </div>`;
  _EDIT_FIELDS.forEach((cfg) => {
    card.querySelector(`[data-f="${cfg.f}"]`).value = v[cfg.f] || "";
  });
  card.querySelector('[data-f="kp"]').value = (v.knowledge_points || []).join("，");
  card.querySelector('[data-f="difficulty"]').value = v.difficulty || "";
  card.querySelector("[data-save]").addEventListener("click", () => {
    _EDIT_FIELDS.forEach((cfg) => {
      v[cfg.f] = card.querySelector(`[data-f="${cfg.f}"]`).value;
    });
    v.knowledge_points = card
      .querySelector('[data-f="kp"]')
      .value.split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    v.difficulty = card.querySelector('[data-f="difficulty"]').value.trim();
    rerender();
    toast("已保存修改（导出/存库将使用新内容）");
  });
  card.querySelector("[data-cancel]").addEventListener("click", rerender);
}

// 按最近一次渲染上下文重绘结果区（编辑后复用）
function rerender() {
  const lr = state.lastRender;
  if (!lr) return;
  if (lr.kind === "paper") renderPaper(lr.groups);
  else renderResults(lr.data);
}

function renderResults(data) {
  copyRegistry = [];
  const checksByIndex = {};
  (data.scope_checks || []).forEach((c) => { checksByIndex[c.index] = c; });
  const ansByIndex = {};
  (data.answer_checks || []).forEach((c) => { ansByIndex[c.index] = c; });
  const symByIndex = {};
  (data.sympy_checks || []).forEach((c) => { symByIndex[c.index] = c; });

  const html = (data.variants || [])
    .map((v, i) =>
      variantCardHtml(v, i + 1, {
        check: checksByIndex[i],
        ans: ansByIndex[i],
        sym: symByIndex[i],
        showBadges: true,
      })
    )
    .join("");
  $("resultsView").innerHTML = html;
  typeset($("resultsView"));
  attachCopyHandlers();
  attachEditHandlers();
  state.lastRender = { kind: "single", data };
}

function renderPaper(groups) {
  copyRegistry = [];
  $("parsedSummary").innerHTML = `<div class="kv"><b>整卷改编</b>共 ${groups.length} 道题（点「导出 Word」组卷下载）</div>`;
  const html = groups
    .map((g, gi) => {
      const orig = g.parsed
        ? `<div class="kv paper-orig"><b>原第 ${gi + 1} 题</b>${escBr(g.parsed.problem_text)}</div>`
        : "";
      const inner = g.error
        ? `<div class="gen-error">本题改编失败：${esc(g.error)}（可单独重试）</div>`
        : (g.variants || [])
            .map((v, vi) => variantCardHtml(v, vi + 1, { showBadges: false }))
            .join("");
      return `<div class="paper-group"><h2 class="paper-h">原第 ${gi + 1} 题改编</h2>${orig}${inner}</div>`;
    })
    .join("");
  $("resultsView").innerHTML = html;
  typeset($("resultsView"));
  typeset($("parsedSummary"));
  attachCopyHandlers();
  attachEditHandlers();
  state.lastRender = { kind: "paper", groups };
}

// ---------- 导出 ----------
async function downloadDocx(url, body, filename) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) showAuth();
  if (!res.ok) {
    let msg = `导出失败 (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch (e) { /* 非 JSON */ }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const dlUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = dlUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(dlUrl);
}

$("exportWordBtn").addEventListener("click", async () => {
  const paper = state.mode === "paper";
  if (paper ? !state.paperGroups : !state.lastResponse) return;
  const btn = $("exportWordBtn");
  setBusy(btn, true, "导出中…");
  try {
    const url = paper ? "/api/export_paper" : "/api/export";
    const body = paper
      ? { groups: state.paperGroups, title: "改编试卷", formula_mode: $("formulaMode").value }
      : {
          parsed: state.parsed,
          variants: state.lastResponse.variants,
          title: "改编题目",
          formula_mode: $("formulaMode").value,
        };
    await downloadDocx(url, body, paper ? "改编试卷.docx" : "改编题目.docx");
    toast("已导出 Word");
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(btn, false, "导出 Word");
  }
});

$("exportBtn").addEventListener("click", () => {
  const payload =
    state.mode === "paper" ? { groups: state.paperGroups } : state.lastResponse;
  if (!payload) return;
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "adapted_problems.json";
  a.click();
  URL.revokeObjectURL(url);
});

// ---------- 题库 ----------
function defaultBankTitle() {
  const p = state.parsed;
  const base = p && p.problem_text ? p.problem_text.replace(/\s+/g, "").slice(0, 12) : "改编结果";
  const d = new Date();
  const ts = `${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `${base}（${ts}）`;
}

async function saveToBank() {
  const lr = state.lastRender;
  if (!lr) {
    toast("请先生成结果再保存");
    return;
  }
  let kind, payload;
  if (lr.kind === "paper") {
    kind = "paper";
    payload = { groups: lr.groups || [] };
  } else {
    kind = "single";
    payload = {
      parsed: state.parsed || null,
      variants: lr.data.variants || [],
      scope_checks: lr.data.scope_checks || [],
      answer_checks: lr.data.answer_checks || [],
    };
  }
  const title = prompt("给这条记录起个名字：", defaultBankTitle());
  if (title === null) return;
  try {
    await postJSON("/api/bank/save", { title: title || "未命名", kind, payload });
    toast("已存入题库");
    loadBankList();
  } catch (err) {
    toast("保存失败：" + err.message);
  }
}

async function loadBankList() {
  try {
    const res = await fetch("/api/bank/list");
    const data = await res.json();
    renderBankList(data.records || []);
  } catch (e) {
    $("bankList").innerHTML = '<p class="hint">题库读取失败。</p>';
  }
}

function renderBankList(records) {
  if (!records.length) {
    $("bankList").innerHTML = '<p class="hint">题库为空，生成结果后点「★ 存入题库」即可保存。</p>';
    return;
  }
  $("bankList").innerHTML = records
    .map(
      (r) => `
    <div class="bank-item" data-id="${r.id}">
      <div class="bank-meta">
        <b>${esc(r.title)}</b>
        <span class="tag">${r.kind === "paper" ? "整卷" : "单题"} · ${r.item_count} 题</span>
        <span class="bank-time">${esc(r.created_at)}</span>
      </div>
      <div class="bank-ops">
        <button class="link" data-load="${r.id}">调回</button>
        <button class="link" data-pick="${r.id}">选题</button>
        <button class="link" data-del="${r.id}">删除</button>
      </div>
    </div>`
    )
    .join("");
  $("bankList")
    .querySelectorAll("[data-load]")
    .forEach((b) => b.addEventListener("click", () => loadBankRecord(b.dataset.load)));
  $("bankList")
    .querySelectorAll("[data-pick]")
    .forEach((b) => b.addEventListener("click", () => openPicker(b.dataset.pick)));
  $("bankList")
    .querySelectorAll("[data-del]")
    .forEach((b) => b.addEventListener("click", () => deleteBankRecord(b.dataset.del)));
}

// ---------- 题库挑题组卷 ----------
// 从一条记录里取出所有题（单题取 variants；整卷把各组 variants 摊平）
function recordVariants(rec) {
  const p = rec.payload || {};
  if (rec.kind === "paper") {
    const out = [];
    (p.groups || []).forEach((g) => (g.variants || []).forEach((v) => out.push(v)));
    return out;
  }
  return p.variants || [];
}

let pickerRegistry = [];
async function openPicker(id) {
  try {
    const res = await fetch(`/api/bank/${id}`);
    const rec = await res.json();
    if (!res.ok) throw new Error(rec.error || "读取失败");
    const vs = recordVariants(rec);
    pickerRegistry = vs;
    $("pickerTitle").textContent = `选题加入组卷 · ${rec.title || ""}`;
    if (!vs.length) {
      $("pickerList").innerHTML = '<p class="hint">这条记录里没有可选的题。</p>';
    } else {
      $("pickerList").innerHTML = vs
        .map(
          (v, i) => `
        <div class="pick-item">
          <div class="pick-stem">${escBr(v.stem)}</div>
          <button class="link" data-add="${i}">＋ 加入组卷</button>
        </div>`
        )
        .join("");
      typeset($("pickerList"));
      $("pickerList")
        .querySelectorAll("[data-add]")
        .forEach((b) =>
          b.addEventListener("click", () => addToCompose(pickerRegistry[Number(b.dataset.add)]))
        );
    }
    $("pickerModal").classList.remove("hidden");
  } catch (err) {
    toast(err.message || "读取失败");
  }
}

function addToCompose(v) {
  if (!v) return;
  state.compose = state.compose || [];
  state.compose.push(JSON.parse(JSON.stringify(v))); // 深拷贝，避免与题库引用纠缠
  renderCompose();
  toast(`已加入组卷（共 ${state.compose.length} 题）`);
}

function renderCompose() {
  const list = state.compose || [];
  const sec = $("step-compose");
  if (!list.length) {
    sec.classList.add("hidden");
    return;
  }
  sec.classList.remove("hidden");
  $("composeCount").textContent = `${list.length} 题`;
  $("composeList").innerHTML = list
    .map(
      (v, i) => `
    <div class="pick-item">
      <div class="pick-stem"><b>第 ${i + 1} 题</b>　${escBr(v.stem)}</div>
      <button class="link" data-remove="${i}">移除</button>
    </div>`
    )
    .join("");
  typeset($("composeList"));
  $("composeList")
    .querySelectorAll("[data-remove]")
    .forEach((b) =>
      b.addEventListener("click", () => {
        state.compose.splice(Number(b.dataset.remove), 1);
        renderCompose();
      })
    );
}

async function exportCompose() {
  const list = state.compose || [];
  if (!list.length) {
    toast("组卷篮是空的");
    return;
  }
  const btn = $("composeExportBtn");
  setBusy(btn, true, "导出中…");
  try {
    await downloadDocx(
      "/api/export",
      {
        parsed: null,
        variants: list,
        title: $("composeTitle").value.trim() || "组卷",
        formula_mode: $("composeFormula").value,
      },
      ($("composeTitle").value.trim() || "组卷") + ".docx"
    );
    toast("已导出组卷 Word");
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(btn, false, "导出组卷 Word");
  }
}

$("pickerCloseBtn").addEventListener("click", () => $("pickerModal").classList.add("hidden"));
$("pickerModal").addEventListener("click", (e) => {
  if (e.target === $("pickerModal")) $("pickerModal").classList.add("hidden");
});
$("composeExportBtn").addEventListener("click", exportCompose);
$("composeClearBtn").addEventListener("click", () => {
  if (!(state.compose || []).length) return;
  if (confirm("清空组卷篮？")) {
    state.compose = [];
    renderCompose();
  }
});

async function loadBankRecord(id) {
  try {
    const res = await fetch(`/api/bank/${id}`);
    const rec = await res.json();
    if (!res.ok) throw new Error(rec.error || "调回失败");
    const p = rec.payload || {};
    if (rec.kind === "paper") {
      state.mode = "paper";
      state.paperGroups = p.groups || [];
      $("parsedSummary").innerHTML = "";
      renderPaper(state.paperGroups);
    } else {
      state.mode = "single";
      state.parsed = p.parsed || null;
      state.lastResponse = { variants: p.variants || [] };
      if (p.parsed) renderParsedSummary(p.parsed);
      else $("parsedSummary").innerHTML = "";
      renderResults({
        variants: p.variants || [],
        scope_checks: p.scope_checks || [],
        answer_checks: p.answer_checks || [],
      });
    }
    show("step-results");
    $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
    toast("已调回：" + (rec.title || ""));
  } catch (err) {
    toast(err.message || "调回失败");
  }
}

async function deleteBankRecord(id) {
  if (!confirm("确认从题库删除这条记录？")) return;
  try {
    const res = await fetch(`/api/bank/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error();
    toast("已删除");
    loadBankList();
  } catch (e) {
    toast("删除失败");
  }
}

$("saveBankBtn").addEventListener("click", saveToBank);
$("refreshBankBtn").addEventListener("click", loadBankList);

// ---------- 在线设置 ----------
function setKeyState(id, ok) {
  const el = $(id);
  el.textContent = ok ? "（已配置）" : "（未配置）";
  el.className = "key-state " + (ok ? "ok" : "bad");
}
function toggleCfgProvider() {
  const p = $("cfgProvider").value;
  $("cfgOpenai").classList.toggle("hidden", p !== "openai");
  $("cfgAnthropic").classList.toggle("hidden", p !== "anthropic");
}
async function refreshConfigBadge() {
  try {
    const res = await fetch("/api/config");
    const c = await res.json();
    state.config = c;
    $("modelBadge").textContent =
      `${c.provider} · ${c.model}` + (c.has_api_key ? "" : " · ⚠未配置key");
  } catch (e) {
    /* 忽略 */
  }
}
async function openSettings() {
  try {
    const res = await fetch("/api/config");
    if (res.status === 401) {
      showAuth();
      return;
    }
    const c = await res.json();
    $("cfgProvider").value = c.provider === "anthropic" ? "anthropic" : "openai";
    $("cfgOpenaiBase").value = c.openai_base_url || "";
    $("cfgOpenaiModel").value = c.openai_model || "";
    $("cfgAnthropicModel").value = c.anthropic_model || "";
    $("cfgOpenaiKey").value = "";
    $("cfgAnthropicKey").value = "";
    setKeyState("cfgOpenaiKeyState", c.has_openai_key);
    setKeyState("cfgAnthropicKeyState", c.has_anthropic_key);
    toggleCfgProvider();
    // 非管理员：只读，隐藏保存
    const admin = !!c.is_admin;
    $("cfgAdminNote").hidden = admin;
    $("cfgSaveBtn").classList.toggle("hidden", !admin);
    ["cfgProvider", "cfgOpenaiBase", "cfgOpenaiModel", "cfgAnthropicModel", "cfgOpenaiKey", "cfgAnthropicKey"].forEach(
      (id) => ($(id).disabled = !admin)
    );
    $("settingsModal").classList.remove("hidden");
  } catch (e) {
    toast("读取设置失败");
  }
}
async function saveSettings() {
  const provider = $("cfgProvider").value;
  const body = {
    LLM_PROVIDER: provider,
    OPENAI_BASE_URL: $("cfgOpenaiBase").value,
    OPENAI_MODEL: $("cfgOpenaiModel").value,
    ADAPT_MODEL: $("cfgAnthropicModel").value,
  };
  const ok = $("cfgOpenaiKey").value;
  const ak = $("cfgAnthropicKey").value;
  if (ok.trim()) body.OPENAI_API_KEY = ok;
  if (ak.trim()) body.ANTHROPIC_API_KEY = ak;
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const c = await res.json();
    if (!res.ok) throw new Error(c.error || "保存失败");
    state.config = c;
    setKeyState("cfgOpenaiKeyState", c.has_openai_key);
    setKeyState("cfgAnthropicKeyState", c.has_anthropic_key);
    $("cfgOpenaiKey").value = "";
    $("cfgAnthropicKey").value = "";
    $("modelBadge").textContent =
      `${c.provider} · ${c.model}` + (c.has_api_key ? "" : " · ⚠未配置key");
    toast("设置已保存，即时生效");
    $("settingsModal").classList.add("hidden");
  } catch (err) {
    toast(err.message || "保存失败");
  }
}
$("settingsBtn").addEventListener("click", openSettings);
$("cfgCloseBtn").addEventListener("click", () => $("settingsModal").classList.add("hidden"));
// 点弹窗外的灰色遮罩也能关闭
$("settingsModal").addEventListener("click", (e) => {
  if (e.target === $("settingsModal")) $("settingsModal").classList.add("hidden");
});
$("cfgProvider").addEventListener("change", toggleCfgProvider);
$("cfgSaveBtn").addEventListener("click", saveSettings);

// ---------- 账号 ----------
let authMode = "login"; // login | register
function showAuth() {
  $("authModal").classList.remove("hidden");
  $("authUser").focus();
}
function setAuthMode(mode) {
  authMode = mode;
  const login = mode === "login";
  $("authTitle").textContent = login ? "登录" : "注册";
  $("authSubmitBtn").textContent = login ? "登录" : "注册";
  $("authToggleBtn").textContent = login ? "没有账号？去注册" : "已有账号？去登录";
  $("authHint").textContent = login
    ? "输入账号密码登录。"
    : "用户名 2–32 位、密码至少 6 位；首位注册的用户将成为管理员。";
  $("authError").classList.add("hidden");
}
async function submitAuth() {
  const username = $("authUser").value.trim();
  const password = $("authPwd").value;
  if (!username || !password) {
    $("authError").textContent = "请填写用户名和密码。";
    $("authError").classList.remove("hidden");
    return;
  }
  try {
    const res = await fetch(`/api/auth/${authMode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || "失败");
    $("authModal").classList.add("hidden");
    $("authPwd").value = "";
    $("authError").classList.add("hidden");
    toast((authMode === "login" ? "登录成功" : "注册成功") + "：" + d.username);
    await afterLogin();
  } catch (err) {
    $("authError").textContent = err.message;
    $("authError").classList.remove("hidden");
  }
}
async function refreshUser() {
  try {
    const res = await fetch("/api/auth/me");
    const d = await res.json();
    return d.user || null;
  } catch (e) {
    return null;
  }
}
function renderUser(u) {
  state.user = u;
  const badge = $("userBadge");
  if (!u) {
    badge.classList.add("hidden");
    $("logoutBtn").classList.add("hidden");
    return;
  }
  const quota =
    u.is_admin || !u.daily_quota
      ? ""
      : ` · 今日 ${u.usage_today}/${u.daily_quota}`;
  badge.textContent = `👤 ${u.username}${u.is_admin ? "（管理员）" : ""}${quota}`;
  badge.classList.remove("hidden");
  $("logoutBtn").classList.remove("hidden");
}
async function afterLogin() {
  const u = await refreshUser();
  renderUser(u);
  if (!u) {
    showAuth();
    return;
  }
  refreshConfigBadge();
  loadBankList();
}
$("authSubmitBtn").addEventListener("click", submitAuth);
$("authToggleBtn").addEventListener("click", () => setAuthMode(authMode === "login" ? "register" : "login"));
$("authPwd").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });
$("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  renderUser(null);
  $("resultsView").innerHTML = "";
  $("bankList").innerHTML = "";
  state.compose = [];
  renderCompose();
  setAuthMode("login");
  showAuth();
});

// ---------- 启动 ----------
setAuthMode("login");
afterLogin();
