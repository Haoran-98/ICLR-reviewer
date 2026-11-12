export async function readManuscriptFile(file) {
  if (!/\.(md|txt|tex|doc|docx|docs|pdf)$/i.test(file.name)) throw new Error('请选择 TXT、Markdown、LaTeX、Word 或 PDF 文件。');
  if (!file.size || file.size > 15 * 1024 * 1024) throw new Error('请选择非空且不超过 15 MB 的文件。');
  if (/\.(md|txt|tex)$/i.test(file.name)) {
    if (file.size > 1_500_000) throw new Error('文本文件请小于 1.5 MB。');
    return { text: await file.text(), converted: false };
  }
  const encoded = await new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = () => reject(new Error('无法读取文件，请重新选择。')); reader.readAsDataURL(file);
  });
  const response = await fetch('/api/review/extract', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, content_base64: encoded }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '文档提取失败，请重试。');
  return { text: result.text, converted: true };
}
