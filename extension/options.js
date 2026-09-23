const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get({ baseUrl: "", apiKey: "" }, ({ baseUrl, apiKey }) => {
    $("base-url").value = baseUrl;
    $("api-key").value = apiKey;
  });

  $("save").addEventListener("click", () => {
    let base = $("base-url").value.trim().replace(/\/+$/, "");
    if (base && !/^https?:\/\//.test(base)) base = `http://${base}`;
    chrome.storage.sync.set(
      { baseUrl: base, apiKey: $("api-key").value.trim() },
      () => {
        $("status").textContent = "Saved!";
        setTimeout(() => ($("status").textContent = ""), 1500);
      }
    );
  });
});
