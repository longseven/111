"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  selectedFile: null,
  parsed: null,
  lastResponse: null,
};

// ---------- 工具 ----------
function toast(msg, ms = 2600) {
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

// ---------- 第 1 步：解析 ----------
$("parseBtn").addEventListener("click", async () => {
  const text = $("pasteText").value.trim();
  if (!state.selectedFile && !text) {
    toast("请上传文件或粘贴题目文本");
    return;
  }
  const btn = $("parseBtn");
  setBusy(btn, true, "解析中…");
  try {
    const form = new FormData();
    if (state.selectedFile) form.append("file", state.selectedFile);
    if (text) form.append("text", text);
    const res = await fetch("/api/parse", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `解析失败 (${res.status})`);
    state.parsed = data;
    renderParsed(data);
    show("step-parsed");
    show("step-conditions");
    $("step-conditions").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(btn, false, "解析原题");
  }
});

function renderParsed(p) {
  const kps = (p.knowledge_points || [])
    .map((k) => `<span class="tag">${esc(k)}</span>`).join("");
  $("parsedView").innerHTML = `
    <div class="kv"><b>题干</b>${esc(p.problem_text)}</div>
    <div class="kv"><b>知识点</b>${kps}</div>
    <div class="kv"><b>学段</b>${esc(p.grade_band)}</div>
    <div class="kv"><b>难度</b>${esc(p.difficulty)}　<b>题型</b>${esc(p.problem_type)}</div>
  `;
}

// ---------- 第 2 步：改编条件 ----------
$("count").addEventListener("input", (e) => {
  $("countLabel").textContent = e.target.value;
});

$("adaptBtn").addEventListener("click", async () => {
  if (!state.parsed) { toast("请先解析原题"); return; }
  const conditions = {
    difficulty_change: $("difficultyChange").value,
    target_type: $("targetType").value,
    scenario_theme: $("scenarioTheme").value.trim(),
    change_mode: $("changeMode").value,
    count: Number($("count").value),
    allow_extension: $("allowExtension").checked,
    grade_hint: "",
  };
  const btn = $("adaptBtn");
  setBusy(btn, true, "生成中…");
  try {
    const data = await postJSON("/api/adapt", {
      parsed: state.parsed,
      conditions,
    });
    state.lastResponse = data;
    renderResults(data);
    show("step-results");
    $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(btn, false, "生成新题");
  }
});

// ---------- 第 3 步：结果 ----------
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
        <div class="field stem"><div class="label">题干</div>${esc(v.stem)}</div>
        <div class="field"><div class="label">参考答案</div>${esc(v.answer)}</div>
        <div class="field"><div class="label">解析</div>${esc(v.solution)}</div>
        <div class="field"><div class="label">知识点</div>${kps}　难度：${esc(v.difficulty)}</div>
        <div class="field reason"><div class="label">改编理由</div>${esc(v.adaptation_reason)}</div>
        <div class="field"><div class="label">不超纲自检</div>${esc(v.within_scope_note)}</div>
        ${checkReason}
        <button class="link" data-copy="${i}">复制本题</button>
      </div>`;
  }).join("");

  $("resultsView").innerHTML = html;

  document.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", () => {
      const v = data.variants[Number(b.dataset.copy)];
      const txt = `${v.stem}\n\n答案：${v.answer}\n解析：${v.solution}`;
      navigator.clipboard.writeText(txt).then(() => toast("已复制到剪贴板"));
    })
  );
}

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
