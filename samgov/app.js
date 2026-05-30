const runButton = document.querySelector("#runButton");
const statusText = document.querySelector("#statusText");

function setStatus(message, type = "default") {
  statusText.textContent = message;
  statusText.classList.toggle("is-error", type === "error");
  statusText.classList.toggle("is-success", type === "success");
}

function getFileName(response) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  return match?.[1] || "samgov_tenders.txt";
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

runButton.addEventListener("click", async () => {
  runButton.disabled = true;
  setStatus("Скрипт запущен. Подождите, файл готовится...");

  try {
    const response = await fetch("/api/run-bot", {
      method: "POST",
      headers: {
        Accept: "text/plain",
      },
    });

    if (!response.ok) {
      let message = "Не удалось выполнить скрипт.";
      try {
        const error = await response.json();
        message = error.message || message;
      } catch {
        message = await response.text();
      }
      throw new Error(message);
    }

    const blob = await response.blob();
    downloadBlob(blob, getFileName(response));
    setStatus("Готово. TXT-файл скачан.", "success");
  } catch (error) {
    setStatus(error.message || "Ошибка запуска. Проверьте Python-сервер.", "error");
  } finally {
    runButton.disabled = false;
  }
});
