function csvEscape(value) {
  const text = String(value ?? "");
  return '"' + text.replaceAll('"', '""') + '"';
}

function resultRows() {
  return [...document.querySelectorAll("#result-table .result-row")].map((row) =>
    [...row.cells].map((cell) => cell.innerText.trim())
  );
}

function resultIds() {
  const ids = resultRows()
    .map((row) => row[1])
    .filter((value) => value && value !== "-");
  return [...new Set(ids)];
}

async function writeClipboardText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  let eventCopied = false;
  const onCopy = (event) => {
    if (event.clipboardData) {
      event.clipboardData.setData("text/plain", text);
      event.preventDefault();
      eventCopied = true;
    }
  };
  document.addEventListener("copy", onCopy);
  const eventExecuted = document.execCommand("copy");
  document.removeEventListener("copy", onCopy);
  if (eventExecuted && eventCopied) {
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("aria-hidden", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  textarea.style.width = "1px";
  textarea.style.height = "1px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) {
    throw new Error("clipboard copy failed");
  }
}

document.addEventListener("click", async (event) => {
  const confirmMessage = event.target.dataset.confirm;
  if (confirmMessage && !window.confirm(confirmMessage)) {
    event.preventDefault();
    return;
  }

  if (event.target.id === "copy-results") {
    const ids = resultIds();
    const original = event.target.textContent;
    if (!ids.length) {
      event.target.textContent = "没有可复制的 ID";
      setTimeout(() => { event.target.textContent = original; }, 1800);
      return;
    }
    try {
      await writeClipboardText(ids.join("\n"));
      event.target.textContent = `已复制 ${ids.length} 个 ID`;
    } catch (_error) {
      event.target.textContent = "复制失败";
    }
    setTimeout(() => { event.target.textContent = original; }, 1500);
  }

  if (event.target.id === "export-results") {
    const headers = ["输入姓名", "用户ID", "性别", "年龄", "年级", "班级", "状态"];
    const rows = resultRows();
    const csv = "\uFEFF" + [headers, ...rows].map((row) => row.map(csvEscape).join(",")).join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "学生ID查询结果.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }
});
