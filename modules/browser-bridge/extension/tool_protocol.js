"use strict";
(function (root) {
  const PREFIX = "[[BCT_TOOL_REQUEST]]";
  const SUFFIX = "[[/BCT_TOOL_REQUEST]]";
  const TOOL = /^[A-Za-z0-9_-]{1,128}$/;
  function parse(text) {
    if (typeof text !== "string" || text.length > 32768) return null;
    const trimmed = text.trim();
    if (!trimmed.startsWith(PREFIX) || !trimmed.endsWith(SUFFIX)) return null;
    const body = trimmed.slice(PREFIX.length, -SUFFIX.length).trim();
    let value;
    try { value = JSON.parse(body); } catch (_) { return null; }
    if (!value || Object.keys(value).sort().join(",") !== "arguments,tool" ||
        !TOOL.test(value.tool || "") || !value.arguments ||
        typeof value.arguments !== "object" || Array.isArray(value.arguments)) return null;
    return Object.freeze({tool: value.tool, arguments: value.arguments});
  }
  root.BctToolProtocol = Object.freeze({parse});
})(globalThis);
