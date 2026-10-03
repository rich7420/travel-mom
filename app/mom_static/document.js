'use strict';
document.getElementById('printDocument').addEventListener('click', () => window.print());
document.getElementById('copyDocument').addEventListener('click', async () => {
  const article = document.getElementById('customerDocument');
  try {
    await navigator.clipboard.writeText(article.innerText);
    document.getElementById('copyStatus').textContent = '已複製對客文字，請核對後由您送出。';
  } catch {
    const range = document.createRange();
    range.selectNodeContents(article);
    const selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(range);
    document.getElementById('copyStatus').textContent = '請手動複製已選取的文字。';
  }
});
