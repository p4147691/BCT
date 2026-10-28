// Header provider buttons: DOM/event ownership with injected Native and status ports.
(() => {
  "use strict";

  const activeBindings = new WeakMap();

  function bind({ button, provider, ports }) {
    if (!button || typeof button.addEventListener !== "function" ||
        typeof button.removeEventListener !== "function") {
      throw new TypeError("Provider launch button is required");
    }
    if (!ports || typeof ports.launch !== "function" || typeof ports.fail !== "function") {
      throw new TypeError("Provider launch requires injected launch and fail ports");
    }

    activeBindings.get(button)?.destroy();
    const google = String(provider || "").toUpperCase() === "GOOGLE";
    const normalizedProvider = google ? "GOOGLE" : "NAVER";
    const name = google ? "Google" : "Naver";
    const type = google ? "launchGoogleChatGpt" : "launchNaverChatGpt";

    button.dataset.provider = normalizedProvider;
    button.textContent = google ? "G+" : "N+";
    button.title = `${name} ChatGPT 새 창 열기`;
    button.setAttribute("aria-label", button.title);
    button.disabled = false;

    const onClick = async () => {
      try {
        const result = await ports.launch({ type });
        if (!result?.ok || !result?.launched) {
          throw new Error(result?.error || `${name} ChatGPT 실행 실패`);
        }
      } catch (error) {
        ports.fail(`${name} ChatGPT 실행 실패 · ${error?.message || error}`);
      }
    };
    button.addEventListener("click", onClick);
    const handle = {
      destroy() {
        button.removeEventListener("click", onClick);
        if (activeBindings.get(button) === handle) activeBindings.delete(button);
      },
    };
    activeBindings.set(button, handle);
    return handle;
  }

  globalThis.MonitorProviderLaunchFeature = Object.freeze({ bind });
})();
