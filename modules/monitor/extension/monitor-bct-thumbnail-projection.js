"use strict";

// Render BCT node labels as one semantic layer above the Native desktop
// capture. This module owns every badge position so legacy per-image
// decorators cannot apply the physical offset a second time.
(function installMonitorBctThumbnailProjection(root) {
  function text(value) {
    return String(value ?? "").trim();
  }

  function positiveNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : 0;
  }

  function geometryFor(img, location, viewport) {
    const left = text(img?.style?.left) || (location
      ? `${((Number(location.left) - viewport.left) / viewport.width) * 100}%`
      : "");
    const top = text(img?.style?.top) || (location
      ? `${((Number(location.top) - viewport.top) / viewport.height) * 100}%`
      : "");
    const width = text(img?.style?.width) || (location
      ? `${(Number(location.width) / viewport.width) * 100}%`
      : "");
    const height = text(img?.style?.height) || (location
      ? `${(Number(location.height) / viewport.height) * 100}%`
      : "");
    return { left, top, width, height };
  }

  function pixels(value, extent) {
    const raw = text(value);
    if (!raw) return 0;
    const number = Number.parseFloat(raw);
    if (!Number.isFinite(number)) return 0;
    return raw.endsWith("%") ? (number / 100) * extent : number;
  }

  function rectanglesOverlap(first, second, gap = 1) {
    return first.left < second.right + gap
      && first.right + gap > second.left
      && first.top < second.bottom + gap
      && first.bottom + gap > second.top;
  }

  function badgeSize(badge) {
    const measured = typeof badge?.getBoundingClientRect === "function"
      ? badge.getBoundingClientRect()
      : null;
    const labelLength = text(badge?.textContent).length;
    return {
      width: positiveNumber(measured?.width) || Math.max(24, 10 + (labelLength * 6.5)),
      height: positiveNumber(measured?.height) || 16,
    };
  }

  function badgeRectangle(windowRectangle, size, anchor, containerSize) {
    const inset = 2;
    const onRight = anchor.endsWith("right");
    const onBottom = anchor.startsWith("bottom");
    const unclampedLeft = onRight
      ? windowRectangle.right - size.width - inset
      : windowRectangle.left + inset;
    const unclampedTop = onBottom
      ? windowRectangle.bottom - size.height - inset
      : windowRectangle.top + inset;
    const left = Math.max(0, Math.min(unclampedLeft, containerSize.width - size.width));
    const top = Math.max(0, Math.min(unclampedTop, containerSize.height - size.height));
    return {
      left,
      top,
      right: left + size.width,
      bottom: top + size.height,
    };
  }

  function arrangeBadges(container, entries) {
    const measured = typeof container?.getBoundingClientRect === "function"
      ? container.getBoundingClientRect()
      : null;
    const containerSize = {
      width: positiveNumber(measured?.width) || positiveNumber(container?.clientWidth) || 320,
      height: positiveNumber(measured?.height) || positiveNumber(container?.clientHeight) || 180,
    };
    const anchors = ["top-left", "top-right", "bottom-left", "bottom-right"];
    const occupied = [];
    let repositioned = 0;
    let unresolved = 0;

    for (const entry of entries) {
      const geometry = entry.geometry;
      const left = pixels(geometry.left, containerSize.width);
      const top = pixels(geometry.top, containerSize.height);
      const windowRectangle = {
        left,
        top,
        right: left + pixels(geometry.width, containerSize.width),
        bottom: top + pixels(geometry.height, containerSize.height),
      };
      const size = badgeSize(entry.badge);
      const candidates = anchors.map((anchor) => ({
        anchor,
        rectangle: badgeRectangle(windowRectangle, size, anchor, containerSize),
      }));
      let selected = candidates.find((candidate) => !occupied.some((rectangle) => (
        rectanglesOverlap(candidate.rectangle, rectangle)
      )));
      if (!selected) {
        selected = candidates
          .map((candidate) => ({
            ...candidate,
            collisions: occupied.filter((rectangle) => rectanglesOverlap(candidate.rectangle, rectangle)).length,
          }))
          .sort((first, second) => first.collisions - second.collisions)[0];
        unresolved += 1;
      }
      entry.badge.dataset.anchor = selected.anchor;
      if (selected.anchor !== "top-left") repositioned += 1;
      occupied.push(selected.rectangle);
    }
    return { repositioned, unresolved };
  }


  const expanded = new WeakMap();
  function highlight(container,key) {
    if(!container)return;
    for(const chip of container.querySelectorAll(".monitor-thumbnail-node-chip")) {
      chip.classList.toggle("is-selected",Boolean(key) && String(chip.dataset.nodeKey||"")===String(key));
    }
  }
  function stackOverlaps(container,layer,entries,images,selectedKey,renderOptions) {
    if(entries.length<2)return {stacked:0,hiddenWindows:0};
    const bounds=container.getBoundingClientRect?.();
    const w=positiveNumber(bounds?.width)||container.clientWidth||320;
    const h=positiveNumber(bounds?.height)||container.clientHeight||180;
    const rect=(item)=>{
      const g=item.geometry,l=pixels(g.left,w),t=pixels(g.top,h);
      return {left:l,top:t,right:l+pixels(g.width,w),bottom:t+pixels(g.height,h)};
    };
    const group=entries.filter((a,i)=>entries.some((b,j)=>
      i!==j && rectanglesOverlap(rect(a),rect(b),0)));
    if(group.length<2)return {stacked:0,hiddenWindows:0};
    const sorted=group.map((entry,i)=>({
      ...entry,order:i,z:positiveNumber(images.get(entry.hwnd)?.dataset?.nativeZIndex)
    })).sort((a,b)=>(b.z-a.z)||(a.order-b.order));
    const trusted=sorted.every(e=>e.z>0);
    const full=expanded.get(container)===true;
    const selected=String(selectedKey||"");
    const shown=sorted.filter((entry,i)=>full||i<3||(selected && entry.badge.querySelectorAll(".monitor-thumbnail-node-chip").some(c=>c.dataset.nodeKey===selected)));
    const doc=container.ownerDocument||root.document;
    const rail=doc.createElement("span");
    rail.className="monitor-thumbnail-z-rail";
    rail.dataset.zOrderConfirmed=String(trusted);
    for(const item of shown){
      const row=doc.createElement("span");
      row.className="monitor-thumbnail-z-row";
      row.dataset.hwnd=item.hwnd;
      const index=doc.createElement("span");
      index.className="monitor-thumbnail-z-index";
      index.textContent=trusted?String(sorted.indexOf(item)+1):"?";
      row.append(index);
      row.append(item.badge);
      rail.append(row);
    }
    const missing=sorted.length-shown.length;
    if(missing||full){
      const more=doc.createElement("button");
      more.type="button";
      more.className="monitor-thumbnail-z-more";
      more.textContent=full?"접기":"+"+missing+"창";
      more.addEventListener?.("pointerdown",e=>e.stopPropagation());
      more.addEventListener?.("click",e=>{
        e.stopPropagation();
        expanded.set(container,!full);
        render(renderOptions);
      });
      rail.append(more);
    }
    layer.append(rail);
    return {stacked:sorted.length,hiddenWindows:missing,zOrderConfirmed:trusted};
  }
  function render(options = {}) {
    const container = options.container;
    if (!container) return Object.freeze({ status: "NO_CONTAINER", candidates: 0, matched: 0, rendered: 0 });
    const state = options.state;
    const locations = options.locations instanceof Map ? options.locations : new Map();
    const numbersForHwnd = typeof options.numbersForHwnd === "function"
      ? options.numbersForHwnd
      : () => [];
    const documentObject = container.ownerDocument || root.document;
    for (const badge of container.querySelectorAll(
      ".monitor-thumbnail-tab-badge, .monitor-window-desktop-badge-thumb, .monitor-window-desktop-badge",
    )) badge.remove();

    let layer = container.querySelector(".monitor-thumbnail-node-overlay");
    if (!layer) {
      layer = documentObject.createElement("span");
      layer.className = "monitor-thumbnail-node-overlay";
      layer.setAttribute("aria-hidden", "true");
    }
    layer.replaceChildren();
    container.append(layer);

    const desktopId = text(container.dataset.desktopId);
    const images = [...container.querySelectorAll(".monitor-desktop-thumb-window[data-hwnd]")];
    const imagesByHwnd = new Map(images
      .map((img) => [text(img.dataset.hwnd), img])
      .filter(([hwnd]) => Boolean(hwnd)));
    const candidates = new Set(imagesByHwnd.keys());
    for (const [hwnd, location] of locations) {
      if (text(location?.desktopId) === desktopId) candidates.add(text(hwnd));
    }

    const viewport = {
      left: Number(container.dataset.monitorPreviewVirtualLeft) || 0,
      top: Number(container.dataset.monitorPreviewVirtualTop) || 0,
      width: Math.max(1, positiveNumber(container.dataset.monitorPreviewVirtualWidth) || 1),
      height: Math.max(1, positiveNumber(container.dataset.monitorPreviewVirtualHeight) || 1),
    };
    let matched = 0;
    let rendered = 0;
    const renderedEntries = [];
    const detailed = typeof options.nodesForHwnd === 'function';
    const skipped = { hidden: 0, minimized: 0, noNumbers: 0, noGeometry: 0 };

    for (const hwnd of candidates) {
      if (!hwnd) continue;
      const img = imagesByHwnd.get(hwnd) || null;
      const location = locations.get(hwnd) || null;
      if (img?.style?.display === "none" || location?.visible === false) {
        skipped.hidden += 1;
        continue;
      }
      if (Boolean(location?.iconic)) {
        skipped.minimized += 1;
        continue;
      }
      const detailedNodes=detailed ? options.nodesForHwnd(hwnd,state) : null;
      const rows=Array.isArray(detailedNodes)?detailedNodes.filter(n=>Number.isSafeInteger(Number(n?.number))&&Number(n.number)>0):[];
      const numbers=detailed ? [...new Set(rows.map(n=>Number(n.number)))]
        : [...new Set(numbersForHwnd(hwnd,state).map(Number).filter(n=>Number.isSafeInteger(n)&&n>0))];
      if (!numbers.length) {
        skipped.noNumbers += 1;
        continue;
      }
      matched += 1;
      const geometry = geometryFor(img, location, viewport);
      if (!geometry.left || !geometry.top || !geometry.width || !geometry.height) {
        skipped.noGeometry += 1;
        continue;
      }

      const windowLayer = documentObject.createElement("span");
      windowLayer.className = "monitor-thumbnail-node-window";
      windowLayer.dataset.hwnd = hwnd;
      Object.assign(windowLayer.style, geometry);
      windowLayer.classList.toggle(
        "monitor-bct-node-target-highlighted",
        Boolean(options.highlightedHwnd) && hwnd === text(options.highlightedHwnd),
      );

      const badge = documentObject.createElement("span");
      badge.className = "monitor-node-number-badge monitor-thumbnail-tab-badge";
      badge.dataset.hwnd = hwnd;
      if(detailed){
        badge.classList.add("monitor-thumbnail-node-chip-list");
        const chosen=String(options.selectedNodeKey||"");
        const selected=rows.find(n=>String(n.key||"")===chosen);
        const displayed=rows.slice(0,3);
        if(selected && !displayed.includes(selected))displayed[Math.max(0,displayed.length-1)]=selected;
        for(const item of displayed){
          const chip=documentObject.createElement("span");
          chip.className="monitor-thumbnail-node-chip";
          chip.dataset.nodeKey=String(item.key||"");
          chip.dataset.number=String(item.number);
          chip.textContent="N"+item.number;
          chip.classList.toggle("is-selected",Boolean(chosen)&&chip.dataset.nodeKey===chosen);
          const activity=String(item.activity||"");
          if(["play","pause","complete"].includes(activity)){
            const status=documentObject.createElement("span");
            status.className="monitor-thumbnail-chip-status";
            status.textContent=activity==="play"?"▶":activity==="pause"?"Ⅱ":"□";
            chip.append(status);
          }
          badge.append(chip);
        }
        if(rows.length>displayed.length){
          const more=documentObject.createElement("span");
          more.className="monitor-thumbnail-node-overflow";
          more.textContent="+"+(rows.length-displayed.length)+"노드";
          badge.append(more);
        }
        badge.title="BCT 노드 "+numbers.join(" / ");
      }else{
        badge.textContent="N"+numbers.join("/");
        badge.title="BCT 노드 "+numbers.join(" / ");
      }
      windowLayer.append(badge);
      layer.append(windowLayer);
      renderedEntries.push({ badge, geometry, hwnd });
      rendered += 1;
    }

    const arrangement = arrangeBadges(container, renderedEntries);
    const stack = detailed ? stackOverlaps(container,layer,renderedEntries,imagesByHwnd,options.selectedNodeKey,options)
      : {stacked:0,hiddenWindows:0,zOrderConfirmed:false};
    if(detailed)highlight(container,options.selectedNodeKey);
    return Object.freeze({
      status: rendered ? "RENDERED" : (matched ? "NO_GEOMETRY" : "NO_MATCH"),
      desktopId,
      candidates: candidates.size,
      matched,
      rendered,
      repositioned: arrangement.repositioned,
      unresolvedCollisions: arrangement.unresolved,
      zStackedWindows:stack.stacked,
      hiddenWindows:stack.hiddenWindows,
      zOrderConfirmed:stack.zOrderConfirmed,
      skipped: Object.freeze(skipped),
    });
  }

  root.MonitorBctThumbnailProjection = Object.freeze({ render, highlight });
})(globalThis);
