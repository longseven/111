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

// ---------- 一键生成 ----------
$("generateBtn").addEventListener("click", async () => {
  const text = $("pasteText").value.trim();
  if (!state.selectedFile && !text) {
    toast("请上传文件或粘贴题目文本");
    return;
  }
  const btn = $("generateBtn");
  setBusy(btn, true, "生成中…（解析→改编→校验）");
  try {
    const form = new FormData();
    if (state.selectedFile) form.append("file", state.selectedFile);
    if (text) form.append("text", text);
    form.append("conditions", JSON.stringify(getConditions()));

    const res = await fetch("/api/generate", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `生成失败 (${res.status})`);

    state.parsed = data.parsed;
    state.lastResponse = { variants: data.variants };
    renderParsedSummary(data.parsed);
    renderResults(data);
    show("step-results");
    $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(btn, false, "生成新题");
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
        <div class="field reason"><div class="label">改编理由</div>${esc(v.adaptation_reason)}</div>
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
