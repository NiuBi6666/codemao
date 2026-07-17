function csvEscape(value) {
  const text = String(value ?? "");
  return '"' + text.replaceAll('"', '""') + '"';
}

function resultRows() {
  return [...document.querySelectorAll("#result-table .result-row")].map((row) =>
    [...row.cells].map((cell) => cell.innerText.trim())
  );
}

document.addEventListener("click", async (event) => {
  const confirmMessage = event.target.dataset.confirm;
  if (confirmMessage && !window.confirm(confirmMessage)) {
    event.preventDefault();
    return;
  }

  if (event.target.id === "copy-results") {
    const rows = resultRows();
    const text = rows.map((row) => row.slice(0, 6).join("\t")).join("\n");
    await navigator.clipboard.writeText(text);
    const original = event.target.textContent;
    event.target.textContent = "已复制";
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
