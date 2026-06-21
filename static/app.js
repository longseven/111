"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  selectedFile: null,
  parsed: null,
  lastResponse: null,
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

const STEP_NAMES = ["识别原题", "改编生成", "不超纲校验"];
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
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

// ---------- 一键生成（分三步显示进度） ----------
$("generateBtn").addEventListener("click", async () => {
  if (!state.selectedFile) {
    toast("请上传题目图片或文件");
    return;
  }
  const btn = $("generateBtn");
  btn.disabled = true;
  clearGenError();
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

    // ② 改编生成
    cur = 1;
    setStep(1, "active");
    const adaptRes = await postJSON("/api/adapt", {
      parsed,
      conditions: getConditions(),
    });
    setStep(1, "done");

    // ③ 不超纲校验
    cur = 2;
    setStep(2, "active");
    const verifyRes = await postJSON("/api/verify", {
      parsed,
      variants: adaptRes.variants,
    });
    setStep(2, "done");

    state.parsed = parsed;
    state.lastResponse = { variants: adaptRes.variants };
    renderParsedSummary(parsed);
    renderResults({ variants: adaptRes.variants, scope_checks: verifyRes.scope_checks });
    show("step-results");
    setTimeout(hideProgress, 700);
    $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    markError();
    showGenError(`【${STEP_NAMES[cur]}】失败：${err.message}\n（详细报错见运行 ./run.sh 的终端窗口）`);
  } finally {
    btn.disabled = false;
  }
});

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
function renderResults(data) {
  const checksByIndex = {};
  (data.scope_checks || []).forEach((c) => { checksByIndex[c.index] = c; });

  const html = (data.variants || []).map((v, i) => {
    const check = checksByIndex[i];
    const passed = check ? check.passed : true;
    const badge = passed
      ? '<span class="badge ok">✓ 不超纲</span>'
      : '<span class="badge bad">✗ 可能超纲</span>';
    const checkReason = check
      ? `<div class="field"><div class="label">校验说明</div>${esc(check.reason)}</div>`
      : "";
    const kps = (v.knowledge_points || [])
      .map((k) => `<span class="tag">${esc(k)}</span>`).join("");
    return `
      <div class="variant ${passed ? "" : "flagged"}">
        <h3>新题 ${i + 1} ${badge}</h3>
        <div class="field stem"><div class="label">题干</div>${escBr(v.stem)}</div>
        <div class="field"><div class="label">参考答案</div>${escBr(v.answer)}</div>
        <div class="field"><div class="label">解析</div>${escBr(v.solution)}</div>
        <div class="field"><div class="label">知识点</div>${kps}　难度：${esc(v.difficulty)}</div>
        <div class="field reason"><div class="label">改编理由</div>${escBr(v.adaptation_reason)}</div>
        <div class="field"><div class="label">不超纲自检</div>${esc(v.within_scope_note)}</div>
        ${checkReason}
        <button class="link" data-copy="${i}">复制本题</button>
      </div>`;
  }).join("");

  $("resultsView").innerHTML = html;
  typeset($("resultsView"));

  document.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", () => {
      const v = data.variants[Number(b.dataset.copy)];
      const txt = `${v.stem}\n\n答案：${v.answer}\n解析：${v.solution}`;
      navigator.clipboard.writeText(txt).then(() => toast("已复制到剪贴板"));
    })
  );
}

// ---------- 导出 ----------
$("exportWordBtn").addEventListener("click", async () => {
  if (!state.lastResponse) return;
  const btn = $("exportWordBtn");
  setBusy(btn, true, "导出中…");
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parsed: state.parsed,
        variants: state.lastResponse.variants,
        title: "改编题目",
        formula_mode: $("formulaMode").value,
      }),
    });
    if (!res.ok) {
      let msg = `导出失败 (${res.status})`;
      try { msg = (await res.json()).error || msg; } catch (e) { /* 非 JSON */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "改编题目.docx";
    a.click();
    URL.revokeObjectURL(url);
    toast("已导出 Word");
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(btn, false, "导出 Word");
  }
});

$("exportBtn").addEventListener("click", () => {
  if (!state.lastResponse) return;
  const blob = new Blob([JSON.stringify(state.lastResponse, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "adapted_problems.json";
  a.click();
  URL.revokeObjectURL(url);
});
