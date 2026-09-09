export const money = (value) =>
  value === null || value === undefined
    ? "—"
    : Number(value || 0).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
export const today = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
export const monthKey = (date = new Date()) =>
  typeof date === "string"
    ? date.slice(0, 7)
    : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
export const monthLabel = (value) => {
  const [year, month] = String(value).split("-");
  return `${year} 年 ${Number(month)} 月`;
};
export const dateTime = (value) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export function downloadCsv(rows, filename) {
  const escape = (value) => {
    let text = String(value ?? "");
    if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const blob = new Blob(
    ["\ufeff", rows.map((row) => row.map(escape).join(",")).join("\r\n")],
    { type: "text/csv;charset=utf-8" },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
