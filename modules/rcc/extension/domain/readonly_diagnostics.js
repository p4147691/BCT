function postNative(message) {
  nativeTransport?.post(message);

}


async function handleNativeCommand(message) {
  await endpointSessionReady;
  if (message?.type !== 'host:command') return;
  const requestId = String(message.requestId || crypto.randomUUID());
  const commandDecision = RccLegacyCommandPolicy.nativeCommand(message.command);
  if (!commandDecision.allowed) {
    postNative({ type: 'host:result', requestId, ok: false, effectState: 'NOT_APPLIED',
      error: RccLegacyCommandPolicy.rejectCode('NATIVE_COMMAND', message.command, commandDecision) });
    return;
  }
  try {
    if (message.command === 'ping') {


          const state = await loadState();


          postNative({ type: 'host:result', requestId, ok: true, pong: true,


            instanceId: state.settings.instanceId, backgroundBuildId: RCC_BACKGROUND_BUILD_ID });


          return;


        }

    if (message.command === 'state') {


          await endpointSessionReady;


          const state = await loadState();


          const chatTabs = await getChatTabs();


          const tabs = chatTabs.map(publicTab);


          const endpoints = await captureEndpointSnapshot('state', chatTabs);


          const coreShadow = coreShadowSnapshot(tabs, endpoints, state.simpleRelayV0Binding);


          postNative({ type: 'host:result', requestId, ok: true, state: {


            instanceId: state.settings.instanceId, sessionId: endpointSessionId, tabs, endpoints,


            registrations: state.registrations, settings: state.settings,


            simpleRelayV0Binding: state.simpleRelayV0Binding,


            coreShadow,


            backgroundBuildId: RCC_BACKGROUND_BUILD_ID


          } });


          return;


        }

    if (message.command === 'simple-relay-bind') {

          const result = await bindSimpleRelayV0(message);

          postNative({ type: 'host:result', requestId, ...result });

          return;

        }

    if (message.command === 'simple-relay-send') {

          const result = await sendSimpleRelayV0(message, requestId);

          postNative({ type: 'host:result', requestId, ...result,

            relayReceipt: publicSimpleRelayV0Receipt(result.receipt) });

          return;

        }

    if (message.command === 'simple-relay-return') {

          const result = await returnSimpleRelayV0(message, requestId);

          postNative({ type: 'host:result', requestId, ...result,

            relayReceipt: publicSimpleRelayV0Receipt(result.receipt) });

          return;

        }

    if (message.command === 'delivery-start') {
          const result = await deliveryStart(message);
          postNative({ type: 'host:result', requestId, sessionId: endpointSessionId, ...result });
          return;
        }

    if (message.command === 'delivery-status') {
          const result = await deliveryStatus(message);
          postNative({ type: 'host:result', requestId, sessionId: endpointSessionId, ...result });
          return;
        }

    if (message.command === 'delivery-return') {
          const result = await deliveryReturn(message);
          postNative({ type: 'host:result', requestId, sessionId: endpointSessionId, ...result });
          return;
        }

    if (message.command === 'new-chat-send') {

          const result = await sendNewChatAndAwaitResult(message);

          postNative({ type: 'host:result', requestId, ...result });

          return;

        }

    if (message.command === 'rename-conversation') {

          const result = await renameConversation(message, requestId);

          postNative({ type: 'host:result', requestId, ...result });

          return;

        }

    if (message.command === 'conversation-bind') {

          const result = await bindExactConversation(message);

          postNative({ type: 'host:result', requestId, ...result });

          return;

        }

    if (message.command === 'send') {
          let result;
          try {
            result = await sendOrchestrationRelay(message, requestId);
          } catch (error) {
            const state = await loadState();
            const effectState = (state.resultReceipts?.[requestId]
              || state.pending?.[requestId]) ? 'UNKNOWN' : 'NOT_APPLIED';
            postNative({ type: 'host:result', requestId, ok: false, effectState,
              ambiguous: effectState === 'UNKNOWN',
              error: String(error?.message || error || 'ORCHESTRATION_RELAY_FAILED') });
            return;
          }
          if (result.ok === false) {
            postNative({ type: 'host:result', requestId, relayId: result.relayId,
              ok: false, effectState: String(result.effectState || 'UNKNOWN'),
              ambiguous: result.effectState !== 'NOT_APPLIED', error: String(result.error || '') });
          } else if (result.completed && result.completedResult) {
            postNative({ type: 'host:result', requestId, relayId: result.relayId,
              ok: true, reply: String(result.completedResult.reply || ''), replayed: true });
          } else if (result.pending && result.submitted !== true) {
            postNative({ type: 'host:result', requestId, relayId: result.relayId,
              ok: false, effectState: 'UNKNOWN', ambiguous: true,
              error: 'ORCHESTRATION_RELAY_DELIVERY_UNCONFIRMED' });
          } else {
            postNative({ type: 'host:ack', requestId, relayId: result.relayId,
              ok: true, submitted: true, effectState: 'SUBMITTED',
              replayed: result.duplicate === true });
          }
          return;
        }

    if (message.command === 'rename-receipt') {

          // Inspection only: never perform or repeat an effect here.

          const relayId = String(message.text || '').trim();

          const tabId = Number(message.tabId);

          const conversationKey = String(message.conversationKey || '');

          if (!relayId || !Number.isSafeInteger(tabId) || tabId <= 0 || !conversationKey) {

            throw new Error('RENAME_RECEIPT_IDENTITY_REQUIRED');

          }

          const state = await loadState();

          // `operations` is a short generic idempotency cache.  Prefer the

          // dedicated rename ledger so unrelated traffic cannot erase recovery

          // evidence, while preserving compatibility with receipts recorded by

          // earlier builds.

          const dedicatedRenameReceipt = state.renameReceipts?.[relayId] || null;

          const record = dedicatedRenameReceipt || state.operations?.[relayId] || null;

          // A reservation contains caller-controlled expected fields so it can

          // reserve storage before UI dispatch.  It is not a terminal receipt and

          // must never be exposed as proof to Core reconciliation.

          const terminal = dedicatedRenameReceipt

            ? dedicatedRenameReceipt.terminal === true : Boolean(record);

          const tab = await browserGateway.getExactTab(tabId).catch(() => null);

          const observed = tab ? {

            tabId: tab.id,

            conversationKey: RelayCore.conversationKey(String(tab.url || '')),

            title: String(tab.title || ''),

            presence: isChatTab(tab) ? 'OPEN' : 'UNKNOWN',

            currentSessionId: endpointSessionId,

          } : null;

          postNative({ type: 'host:result', requestId, ok: true,

            instanceId: state.settings.instanceId, relayId,

            receipt: terminal && record ? { command: record.command,

              fingerprint: record.fingerprint, result: record.result } : null,

            receiptState: terminal ? 'TERMINAL' : (record ? 'PREPARED' : 'MISSING'),

            observed });

          return;

        }

    if (message.command === 'result') {


          const relayId = String(message.text || message.relayId || '').trim();


          if (!relayId) throw new Error('RELAY_ID_REQUIRED');


          const state = await loadState();


          const receipt = state.resultReceipts?.[relayId] || null;


          const newChatReceipt = state.newChatReceipts?.[relayId] || null;


          const completed = publicResultFromReceipt(receipt) ||


            (state.results || []).find((item) => String(item?.id || '') === relayId) ||


            await recoverPersistedNewChatResult(state, relayId) || null;


          const newChatPendingStatus = completed ? null


            : publicPendingNewChatStatus(newChatReceipt);


          const pending = completed ? null : newChatPendingStatus ||


            state.pending?.[relayId] || null;


          postNative({ type: 'host:result', requestId, ok: true, relayId, found: !!completed,


            completed: !!completed, pending: !!pending, result: completed,


            pendingStatus: newChatPendingStatus || (pending ? { to: String(pending.to || ''), createdAt: Number(pending.createdAt || 0) || null,


              acceptedAt: Number(pending.acceptedAt || 0) || null, submittedAt: Number(pending.submittedAt || 0) || null,


              deliveryConfirmed: pending.deliveryConfirmed === true, deferred: pending.deferred === true,


              networkStartedAt: Number(pending.networkStartedAt || 0) || null,


              networkCompletedAt: Number(pending.networkCompletedAt || 0) || null } : null) });


          return;


        }

    if (message.command === 'main-capture-get') {


          const reg=await resolveRegistration(message.to); const x=await browserGateway.executeScript({target:{tabId:reg.tabId},world:'MAIN',func:()=>window.__dwRelayCaptured||[]}); postNative({type:'host:result',requestId,ok:true,captured:x?.[0]?.result||[]}); return;


        }

    if (message.command === 'api-probe') {


          const reg = await resolveRegistration(message.to);


          const key = String(reg.conversationKey || '');


          const injected = await browserGateway.executeScript({ target: { tabId: reg.tabId }, func: async (conversationKey) => {


            const urls=[`/backend-api/conversation/${conversationKey}`,`/backend-api/conversations/${conversationKey}`]; const out=[];


            for (const url of urls) { try { const r=await fetch(url,{credentials:'include',cache:'no-store'}); const text=await r.text(); out.push({url,status:r.status,ok:r.ok,preview:text.slice(0,800)}); } catch (e) { out.push({url,error:String(e?.message||e)}); } }


            return out;


          }, args: [key] });


          postNative({ type:'host:result', requestId, ok:true, role:RelayCore.normalizeRole(message.to), api:injected?.[0]?.result || [] });


          return;


        }

    if (message.command === 'probe-tabs') {

          const tabs = (await getChatTabs()).filter(isChatTab);

          const probes = [];

          for (const tab of tabs) {

            let probe = null;

            let error = '';

            try {

              probe = await browserGateway.sendMessage(tab.id, { type: 'relay:probe' });

            } catch (err) {

              error = String(err?.message || err);

            }

            probes.push({

              tabId: tab.id,

              windowId: tab.windowId,

              conversationKey: RelayCore.conversationKey(tab.url || ''),

              title: tab.title || '',

              ok: probe?.ok === true,

              buildVersion: String(probe?.buildVersion || ''),

              contentVersion: String(probe?.contentVersion || ''),

              error

            });

          }

          postNative({ type: 'host:result', requestId, ok: true, probes });

          return;

        }

    if (message.command === 'diagnose-activity') {


          const key = String(message.text || '').trim();


          const tabs = (await getChatTabs()).filter((tab) => !key || RelayCore.conversationKey(tab?.url || '') === key);


          const diagnostics = [];


          for (const tab of tabs) {


            try {


              const result = await browserGateway.executeScript({ target: { tabId: tab.id }, func: () => {


                const items = [...document.querySelectorAll('button,[data-testid],[aria-label]')].map((el) => ({


                  tag: el.tagName, testid: el.getAttribute('data-testid') || '', aria: el.getAttribute('aria-label') || '',


                  title: el.getAttribute('title') || '', text: String(el.textContent || '').trim().slice(0,80), disabled: !!el.disabled


                }));


                return items.filter((x) => /stop|cancel|send|submit|voice|record|generat|중지|전송|음성|보내/i.test([x.testid,x.aria,x.title,x.text].join(' '))).slice(0,80);


              }});


              diagnostics.push({ tabId: tab.id, conversationKey: RelayCore.conversationKey(tab.url || ''), title: tab.title || '', items: result?.[0]?.result || [] });


            } catch (error) { diagnostics.push({ tabId: tab.id, error: String(error?.message || error) }); }


          }


          postNative({ type: 'host:result', requestId, ok: true, diagnostics });


          return;


        }

    if (message.command === 'diagnose-conversation-ui') {

          const key = String(message.conversationKey || message.text || '').trim();

          const tabs = (await getChatTabs()).filter((tab) => !key || RelayCore.conversationKey(tab?.url || '') === key);

          const diagnostics = [];

          for (const tab of tabs) {

            try {

              const result = await browserGateway.executeScript({

                target: { tabId: tab.id },

                func: () => {

                  const visible = (el) => {

                    if (!el || el.getClientRects().length === 0) return false;

                    const rect = el.getBoundingClientRect();

                    if (rect.width <= 0 || rect.height <= 0) return false;

                    const style = getComputedStyle(el);

                    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) !== 0;

                  };

                  const pack = (el) => {

                    const rect = el.getBoundingClientRect();

                    return {

                      tag: el.tagName,

                      role: el.getAttribute('role') || '',

                      href: el.getAttribute('href') || '',

                      testid: el.getAttribute('data-testid') || '',

                      sidebar: el.getAttribute('data-sidebar-item') || '',

                      aria: el.getAttribute('aria-label') || '',

                      title: el.getAttribute('title') || '',

                      text: String(el.textContent || '').replace(/\s+/g,' ').trim().slice(0,120),

                      left: Math.round(rect.left), top: Math.round(rect.top),

                      width: Math.round(rect.width), height: Math.round(rect.height)

                    };

                  };

                  const rowSelector = '[data-sidebar-item="true"], nav li, aside li';

                  const rows = Array.from(document.querySelectorAll(rowSelector)).filter(visible).map(pack).slice(0,120);

                  const links = Array.from(document.querySelectorAll('a[href]')).filter((el) => {

                    if (!visible(el)) return false;

                    const href = String(el.getAttribute('href') || '');

                    return /\/c\/[a-z0-9-]{8,64}/i.test(href);

                  }).map(pack).slice(0,120);

                  const buttons = Array.from(document.querySelectorAll('button')).filter((el) => {

                    if (!visible(el) || el.disabled) return false;

                    const text = [el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('data-testid'),el.textContent].filter(Boolean).join(' ');

                    return /sidebar|side bar|menu|more|options|chat|conversation|history|사이드|메뉴|옵션|더 보기|대화|채팅/i.test(text);

                  }).map(pack).slice(0,120);

                  const assistantSelector = [

                    '[data-message-author-role="assistant"]',

                    '[data-content-search-unit-key$=":assistant"]',

                    '[data-chatgpt-search-unit-key$=":assistant"]',

                    '[data-markdown-text-style="assistant-message"]'

                  ].join(',');

                  const userSelector = [

                    '[data-message-author-role="user"]',

                    '[data-content-search-unit-key$=":user"]',

                    '[data-user-message-bubble="true"]'

                  ].join(',');

                  const userNodes = Array.from(document.querySelectorAll(userSelector));

                  const userUnits = userNodes.map((el, index) => {

                    const closestTurn = el.closest('[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]');

                    const clone = el.cloneNode(true);

                    clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());

                    return {

                      index,

                      visible: visible(el),

                      turnKey: closestTurn?.getAttribute('data-turn-key') || closestTurn?.getAttribute('data-content-search-turn-key') || closestTurn?.getAttribute('data-testid') || '',

                      textLength: String(clone.textContent || '').trim().length,

                      textPreview: String(clone.textContent || '').replace(/\s+/g,' ').trim().slice(0,260),

                      textFull: String(clone.textContent || '').trim()

                    };

                  }).slice(-40);

                  const assistantNodes = Array.from(document.querySelectorAll(assistantSelector));

                  const assistantUnits = assistantNodes.map((el, index) => {

                    const closestTurn = el.closest('[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]');

                    return {

                      index,

                      visible: visible(el),

                      tag: el.tagName,

                      authorRole: el.getAttribute('data-message-author-role') || '',

                      unitKey: el.getAttribute('data-content-search-unit-key') || el.getAttribute('data-chatgpt-search-unit-key') || '',

                      markdownStyle: el.getAttribute('data-markdown-text-style') || '',

                      turnKey: closestTurn?.getAttribute('data-turn-key') || closestTurn?.getAttribute('data-content-search-turn-key') || closestTurn?.getAttribute('data-testid') || '',

                      nestedAssistantCount: el.querySelectorAll(assistantSelector).length,

                      textLength: String(el.innerText || el.textContent || '').trim().length,

                      textPreview: String(el.innerText || el.textContent || '').replace(/\s+/g,' ').trim().slice(0,160)

                    };

                  }).slice(-40);

                  let relayExecution = null;

                  try {

                    const raw = sessionStorage.getItem('relayActiveExecutionV1');

                    const parsed = raw ? JSON.parse(raw) : null;

                    if (parsed && typeof parsed === 'object') {

                      relayExecution = {

                        relayId: String(parsed.relayId || ''),

                        conversationKey: String(parsed.conversationKey || ''),

                        routeTurnKey: String(parsed.routeTurnKey || ''),

                        phase: String(parsed.phase || ''),

                        submittedAt: parsed.submittedAt || null,

                        beforeTurnKeys: Array.isArray(parsed.beforeTurnKeys) ? parsed.beforeTurnKeys.slice(-8) : []

                      };

                    }

                  } catch (_) {}

                  return { href: location.href, documentTitle: document.title, rows, links, buttons, userUnits, assistantUnits, relayExecution };

                }

              });

              diagnostics.push({

                tabId: tab.id,

                conversationKey: RelayCore.conversationKey(tab.url || ''),

                title: tab.title || '',

                ui: result?.[0]?.result || null

              });

            } catch (error) {

              diagnostics.push({ tabId: tab.id, error: String(error?.message || error) });

            }

          }

          let recoveryProbe = null;

          const probeRelayId = String(message.relayId || '').trim();

          const probeRole = String(message.to || '').trim();

          if (probeRelayId && probeRole) {

            try {

              const data = await stateRepository.getLocal([RELAY_RESULT_RECEIPTS_KEY]);

              const probeReceipt = (data[RELAY_RESULT_RECEIPTS_KEY] || {})[probeRelayId] || null;

              const probeReg = await resolveRegistration(probeRole);

              let submittedText = '';

              try {

                const parts = JSON.parse(String(probeReceipt?.dispatchFingerprint || ''));

                if (Array.isArray(parts) && typeof parts[1] === 'string') submittedText = parts[1];

              } catch (_) {}

              const recovered = await recoverCompletedReplyDirectlyFromTab(

                probeReg.tabId, probeReg.conversationKey, submittedText

              );

              recoveryProbe = {

                ok: recovered?.ok === true,

                replyLength: String(recovered?.recoveredReply || '').length,

                replyPreview: String(recovered?.recoveredReply || '').slice(0, 220)

              };

            } catch (error) {

              let comparison = null;

              try {

                const compare = await browserGateway.executeScript({

                  target: { tabId: probeReg.tabId },

                  args: [submittedText],

                  func: (submittedRaw) => {

                    const norm = (value) => String(value || '').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();

                    const submitted = norm(submittedRaw);

                    const turns = Array.from(document.querySelectorAll(

                      '[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]'

                    ));

                    const seen = new Set();

                    const rows = [];

                    for (const node of turns) {

                      const turn = node.matches('[data-turn-key]') ? node : (node.closest('[data-turn-key]') || node);

                      if (seen.has(turn)) continue;

                      seen.add(turn);

                      const user = turn.querySelector(

                        '[data-message-author-role="user"],[data-content-search-unit-key$=":user"],[data-user-message-bubble="true"]'

                      );

                      if (!user) continue;

                      const clone = user.cloneNode(true);

                      clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());

                      const rendered = norm(clone.textContent || '');

                      let diff = -1;

                      const min = Math.min(submitted.length, rendered.length);

                      for (let i = 0; i < min; i += 1) {

                        if (submitted[i] !== rendered[i]) { diff = i; break; }

                      }

                      if (diff < 0 && submitted.length !== rendered.length) diff = min;

                      rows.push({

                        turnKey: turn.getAttribute('data-turn-key') || turn.getAttribute('data-content-search-turn-key') || turn.getAttribute('data-testid') || '',

                        submittedLength: submitted.length,

                        renderedLength: rendered.length,

                        diff,

                        submittedChar: diff >= 0 ? submitted.charCodeAt(diff) : null,

                        renderedChar: diff >= 0 ? rendered.charCodeAt(diff) : null,

                        submittedAround: diff >= 0 ? submitted.slice(Math.max(0,diff-20),diff+21) : '',

                        renderedAround: diff >= 0 ? rendered.slice(Math.max(0,diff-20),diff+21) : ''

                      });

                    }

                    return rows;

                  }

                });

                comparison = compare?.[0]?.result || null;

              } catch (_) {}

              recoveryProbe = { ok: false, error: String(error?.message || error || ''), comparison };

            }

          }

          postNative({ type: 'host:result', requestId, ok: true, diagnostics, recoveryProbe });

          return;

        }

    if (message.command === 'diagnose-composer') {

          const tabs = (await getChatTabs()).filter(isChatTab);

          const diagnostics = [];

          for (const tab of tabs) {

            try {

              const result = await browserGateway.executeScript({

                target: { tabId: tab.id },

                func: () => {

                  const selectors = [

                    '#prompt-textarea',

                    'div[contenteditable="true"][role="textbox"]',

                    'div[contenteditable="true"][data-virtualkeyboard="true"]',

                    'textarea[name="prompt-textarea"]'

                  ];

                  let editor = null;

                  for (const selector of selectors) {

                    editor = document.querySelector(selector);

                    if (editor) break;

                  }

                  const form = editor?.closest?.('form') || null;

                  const buttons = Array.from((form || document).querySelectorAll('button')).map((button) => ({

                    type: button.getAttribute('type') || '',

                    testid: button.getAttribute('data-testid') || '',

                    aria: button.getAttribute('aria-label') || '',

                    title: button.getAttribute('title') || '',

                    text: String(button.textContent || '').trim().slice(0, 80),

                    disabled: !!button.disabled,

                    visible: button.getClientRects().length > 0

                  })).slice(0, 80);

                  return {

                    href: location.href,

                    editor: editor ? {

                      tag: editor.tagName,

                      value: typeof editor.value === 'string' ? editor.value : '',

                      text: String(editor.innerText || editor.textContent || ''),

                      html: String(editor.innerHTML || '').slice(0, 1500),

                      contenteditable: editor.getAttribute('contenteditable') || '',

                      role: editor.getAttribute('role') || '',

                      testid: editor.getAttribute('data-testid') || '',

                      aria: editor.getAttribute('aria-label') || '',

                      placeholder: editor.getAttribute('placeholder') || editor.getAttribute('data-placeholder') || ''

                    } : null,

                    form: form ? {

                      method: form.getAttribute('method') || '',

                      action: form.getAttribute('action') || '',

                      text: String(form.textContent || '').trim().slice(0, 300)

                    } : null,

                    buttons

                  };

                }

              });

              diagnostics.push({ tabId: tab.id, title: tab.title || '', url: tab.url || '', result: result?.[0]?.result || null });

            } catch (error) {

              diagnostics.push({ tabId: tab.id, title: tab.title || '', url: tab.url || '', error: String(error?.message || error) });

            }

          }

          postNative({ type: 'host:result', requestId, ok: true, diagnostics });

          return;

        }

    if (message.command === 'probe') {


          const reg = await resolveRegistration(message.to);


          const probe = await sendToChatTab(reg.tabId, { type: 'relay:probe' });


          const state = await loadState();


          const pending = Object.entries(state.pending || {}).filter(([, item]) => Number(item?.tabId) === Number(reg.tabId)).map(([relayId, item]) => ({


            relayId, deliveryConfirmed: item?.deliveryConfirmed === true,


            networkPath: String(item?.networkPath || ''), networkRequestId: String(item?.networkRequestId || ''),


            networkStartedAt: Number(item?.networkStartedAt || 0) || null,


            networkCompletedAt: Number(item?.networkCompletedAt || 0) || null,


            networkOk: item?.networkOk !== false, networkCandidates: Array.isArray(item?.networkCandidates) ? item.networkCandidates : [], createdAt: Number(item?.createdAt || 0) || null


          }));


          postNative({ type: 'host:result', requestId, ok: true, role: RelayCore.normalizeRole(message.to), probe, pending });


          return;


        }

    if (message.command === 'reload-extension') {


          postNative({ type: 'host:result', requestId, ok: true, reloading: true });


          lifecycle.reload(50);


          return;


        }
    throw new Error(`Unknown native command: ${message.command}`);
  } catch (error) {
    postNative({ type: 'host:result', requestId, ok: false, error: error.message });
  }
}
