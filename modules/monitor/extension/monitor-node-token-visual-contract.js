"use strict";

// One read-only presentation contract reused by window thumbnails and D# minimized labels.
// Role authority comes exclusively from the current Monitor BCT node's roleTags.
(function installMonitorNodeTokenVisualContract(root) {
  function roleFor(node) {
    const tags = Array.isArray(node?.roleTags) ? node.roleTags
      .map((tag) => String(tag || "").trim().toLowerCase()) : [];
    // Bad input cannot decorate an unrelated node; a conflicting role is not
    // something the thumbnail layer is authorized to repair.
    if (tags.includes("manager") && tags.includes("supervisor")) return "";
    if (tags.includes("supervisor")) return "supervisor";
    if (tags.includes("manager")) return "manager";
    return "";
  }
  function activityFor(report) {
    const kind = String(report?.kind || "").trim().toLowerCase();
    if (["working", "running"].includes(kind)) return "working";
    if (["ready", "completed", "complete"].includes(kind)) return "ready";
    if (["abnormal", "stopped", "failed"].includes(kind)) return "abnormal";
    return "";
  }
  function classesFor(node, report, selected) {
    const result = [];
    const activity = activityFor(report);
    const role = roleFor(node);
    if (role) result.push("is-role-" + role);
    if (activity) result.push("has-report", "is-" + activity);
    if (selected === true) result.push("is-selected");
    return result;
  }
  function shouldAcknowledge(report) {
    return ["ready", "abnormal"].includes(activityFor(report))
      && Boolean(String(report?.conversationKey || "").trim());
  }
  root.MonitorNodeTokenVisualContract = Object.freeze({
    roleFor, activityFor, classesFor, shouldAcknowledge,
  });
})(globalThis);
