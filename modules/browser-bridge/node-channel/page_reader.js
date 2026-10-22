"use strict";
// This function executes inside the requested ChatGPT tab on an explicit
// read-only request. No click, text input, storage, postMessage or fetch.
function bctIndependentReadNode(expectedConversationKey) {
  const actual = /^\/c\/([a-f0-9-]{36})\/?$/.exec(location.pathname)?.[1]||"";
  if(location.protocol!=="https:"||location.hostname!=="chatgpt.com"
      ||actual!==expectedConversationKey)
    return {ok:false,error:"NODE_PAGE_IDENTITY_CHANGED"};
  const role = value => [...document.querySelectorAll(
    '[data-message-author-role="'+value+'"]'
  )].filter(element=>!element.parentElement?.closest(
      '[data-message-author-role="'+value+'"]'));
  const assistant = role("assistant"), user=role("user");
  const latest = assistant.at(-1);
  const txt = latest?.innerText||latest?.textContent||"";
  const generating = !!document.querySelector(
    'button[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="중지"]');
  return {ok:true,conversationKey:actual, generating,
    userCount:user.length,assistantCount:assistant.length,
    lastAssistant:String(txt).trim().slice(0,2400)};
}
if(typeof module!=="undefined"&&module.exports)module.exports=bctIndependentReadNode;
