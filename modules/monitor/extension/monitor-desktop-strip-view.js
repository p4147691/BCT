// DesktopStrip DOM surface. Owns card creation/removal and event binding;
// the one desktop identity and Native operations remain injected ports.
(() => {
  "use strict";
  function create({root,document,ports}) {
    if (!root || !document || !ports) throw new TypeError("DESKTOP_STRIP_PORTS_REQUIRED");
function sync() {
  const createdDesktopIds = [];

  const existing = new Map([...root.children].filter(button => !button.dataset.deletedPlaceholder).map(button => [button.dataset.desktopId, button]));

  for (let index = 0; index < ports.desktopState().count; index += 1) {

    const desktopId = ports.desktopState().desktopIds[index] || `index-${index}`;

    let button = existing.get(desktopId);

    if (!button) {

      button = document.createElement("button"); button.type = "button"; button.className = "monitor-desktop-thumb"; button.dataset.desktopId = desktopId;

      const visual = document.createElement("span"); visual.className = "monitor-desktop-thumb-visual"; visual.dataset.desktopId = desktopId;

      const label = document.createElement("span"); label.className = "monitor-desktop-thumb-label";

      const desktopBadge = document.createElement("span"); desktopBadge.className = "monitor-desktop-number-badge";

      const labelText = document.createElement("span"); labelText.className = "monitor-desktop-label-text";

      const minimizedNodes = document.createElement("span"); minimizedNodes.className = "monitor-desktop-minimized-nodes"; minimizedNodes.hidden = true;

      label.append(desktopBadge, labelText, minimizedNodes);
      ports.attachManagement(label, desktopId);

      button.append(visual, label);

      button.addEventListener("pointerdown", ports.beginDrag);

      button.addEventListener("click", (event) => {

        if (button.dataset.monitorDropSuppressClick === "1") { event.preventDefault(); event.stopPropagation(); return; }

        ports.preview(Number(button.dataset.index || 0));

      });

      button.addEventListener("dblclick", async (event) => {

        event.preventDefault();

        const index = Number(button.dataset.index || 0);

        button.classList.add("monitor-desktop-switch-pending");

        try {

          const result = await ports.switchDesktop(index);

          if (!result?.ok) throw new Error(result?.error || "데스크톱 전환 실패");

          ports.renderDesktops(result);

          ports.preview(index);

        } catch (error) { ports.status(`데스크톱 전환 실패 · ${error?.message || error}`, false); }

        finally { ports.after(() => button.classList.remove("monitor-desktop-switch-pending"), 350); }

      });

      ports.bindDrop(button);

      root.append(button);
      createdDesktopIds.push(desktopId);

    }

    button.dataset.index = String(index); button.classList.toggle("selected", index === ports.desktopState().selectedIndex); button.classList.toggle("current", index === ports.desktopState().currentIndex);
    ports.attachManagement(button.querySelector(".monitor-desktop-thumb-label"), desktopId);

    const displayIndex = ports.deletedUndo() && Date.now() < ports.deletedUndoExpiresAt() && index >= Number(ports.deletedUndo().index) ? index + 1 : index;

    const labelText=button.querySelector(".monitor-desktop-label-text"); if(labelText)labelText.textContent=`데스크톱 ${displayIndex + 1}`; const desktopBadge=button.querySelector(".monitor-desktop-number-badge"); if(desktopBadge)desktopBadge.textContent=`D${displayIndex + 1}`;

    existing.delete(desktopId);

  }

  for (const stale of existing.values()) { const key=String(stale.dataset.hwnd||""); stale.parentElement?.querySelectorAll(".monitor-window-pause-overlay").forEach((node)=>{if(node.dataset.hwnd===key)node.remove();}); stale.remove(); }

  for (const stalePlaceholder of [...root.querySelectorAll(".monitor-desktop-trash-placeholder")]) stalePlaceholder.remove();

  if (ports.deletedUndo() && Date.now() < ports.deletedUndoExpiresAt()) {

    const placeholder=document.createElement("div"); placeholder.className="monitor-desktop-thumb monitor-desktop-trash-placeholder"; placeholder.dataset.deletedPlaceholder="1";

    const undo=document.createElement("button"); undo.type="button"; undo.className="monitor-desktop-trash-placeholder-undo"; undo.title="삭제한 데스크톱 되돌리기"; undo.setAttribute("aria-label","삭제한 데스크톱 되돌리기");

    const icon=document.createElement("span"); icon.className="monitor-desktop-trash-placeholder-icon"; icon.textContent="↶";

    const countdown=document.createElement("span"); countdown.className="monitor-desktop-trash-placeholder-countdown"; countdown.textContent=`${Math.max(0,Math.ceil((ports.deletedUndoExpiresAt()-Date.now())/1000))}s`;

    undo.append(icon,countdown); undo.addEventListener("click", ports.undoDelete); placeholder.append(undo);

    const at=Math.max(0,Math.min(Number(ports.deletedUndo().index)||0,root.children.length));

    root.insertBefore(placeholder,root.children[at]||null);

  }

  // Background identity is the desktop GUID, not the Monitor popup's owning
  // desktop. Every new canonical card enters the same bottom-layer port used
  // by the lightweight renderer; V2 coalesces startup overlap per tile.
  if (createdDesktopIds.length) ports.frame(() => {
    const renderer = ports.thumbnail();
    for (const desktopId of createdDesktopIds) {
      const tile = [...root.children].find((item) => (
        String(item.dataset.desktopId || "") === String(desktopId)
      ));
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (visual?.isConnected) void renderer?.refreshBackground?.(visual, desktopId).catch(() => null);
    }
  });
  if (ports.thumbnail()?.allowsLayer?.("summary") !== false) ports.syncBadges();
  ports.frame(ports.syncScrollArrows);

}

    return Object.freeze({sync});
  }
  globalThis.MonitorDesktopStripView=Object.freeze({create});
})();
