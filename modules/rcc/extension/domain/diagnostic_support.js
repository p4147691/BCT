async function recoverCompletedReplyDirectlyFromTab(tabId, conversationKey, submittedText) {
  const tab = await browserGateway.getExactTab(tabId);
  if (!isChatTab(tab) || RelayCore.conversationKey(tab.url || '') !== String(conversationKey || '')) {
    throw new Error('RELAY_RECOVERY_DIRECT_IDENTITY_MISMATCH');
  }
  const injected = await browserGateway.executeScript({
    target: { tabId },
    args: [String(submittedText || '')],
    func: (submittedRaw) => {
      const normalize = (value) => String(value || '')
        .replace(/\u00a0/g, ' ')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n[ \t]+/g, '\n')
        .replace(/[ \t]{2,}/g, ' ')
        .trim();
      const visible = (el) => !!(
        el && el.getClientRects().length > 0
        && getComputedStyle(el).visibility !== 'hidden'
        && getComputedStyle(el).display !== 'none'
      );
      const nodes = Array.from(document.querySelectorAll(
        '[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]'
      ));
      const turns = [];
      const seen = new Set();
      for (const node of nodes) {
        const keyedDescendants = Array.from(node.querySelectorAll?.('[data-turn-key]') || []);
        const turn = node.matches('[data-turn-key]')
          ? node
          : (node.closest('[data-turn-key]')
            || (keyedDescendants.length === 1 ? keyedDescendants[0] : node));
        if (seen.has(turn)) continue;
        seen.add(turn);
        turns.push(turn);
      }
      const submitted = normalize(submittedRaw);
      const submittedInline = normalize(submittedRaw.replace(/`([^`\r\n]+)`/g, '$1'));
      const compareCanonical = (value) => normalize(value).replace(/\s+/g, ' ');
      const submittedCanonical = compareCanonical(submitted);
      const submittedInlineCanonical = compareCanonical(submittedInline);
      const userText = (turn) => {
        const unit = turn.querySelector(
          '[data-message-author-role="user"],[data-content-search-unit-key$=":user"],[data-user-message-bubble="true"]'
        );
        if (!unit) return '';
        const content = unit.querySelector('[data-user-message-bubble="true"],[data-message-author-role="user"]') || unit;
        const clone = content.cloneNode(true);
        clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());
        // Keep this exact UI-decoration rule aligned with messageUnitText.
        clone.querySelectorAll('[data-search-result-target] + span[aria-hidden="true"]').forEach((item) => {
          if (item.textContent === '…') item.remove();
        });
        return normalize(clone.textContent || '');
      };
      const matches = turns.filter((turn) => {
        const rendered = userText(turn);
        if (!rendered) return false;
        const renderedCanonical = compareCanonical(rendered);
        return rendered === submitted
          || rendered === submittedInline
          || renderedCanonical === submittedCanonical
          || renderedCanonical === submittedInlineCanonical;
      });
      if (matches.length !== 1) {
        return { ok: false, error: matches.length > 1 ? 'RELAY_RECOVERY_DIRECT_TURN_AMBIGUOUS' : 'RELAY_RECOVERY_DIRECT_TURN_NOT_FOUND' };
      }
      const turn = matches[0];
      const turnState = String(
        turn.getAttribute('data-talvt-turn-state')
        || turn.querySelector('[data-talvt-turn-state]')?.getAttribute('data-talvt-turn-state')
        || ''
      ).trim().toLowerCase();
      if (/^(interrupted|cancelled|canceled|error|failed)$/.test(turnState)) {
        return { ok: false, error: 'RELAY_RECOVERY_DIRECT_INTERRUPTED' };
      }
      if (turn.querySelector(
        'button[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label="중지"],button[aria-label*="응답 중지"]'
      )) {
        return { ok: false, error: 'RELAY_RECOVERY_DIRECT_STILL_STREAMING' };
      }
      const assistantSelector = [
        '[data-message-author-role="assistant"]',
        '[data-content-search-unit-key$=":assistant"]',
        '[data-chatgpt-search-unit-key$=":assistant"]',
        '[data-markdown-text-style="assistant-message"]'
      ].join(',');
      const assistantNodes = Array.from(turn.querySelectorAll(assistantSelector)).filter(visible);
      const leafUnits = assistantNodes.filter((unit) =>
        !assistantNodes.some((other) => other !== unit && unit.contains(other))
      );
      if (!leafUnits.length) return { ok: false, error: 'RELAY_RECOVERY_DIRECT_ASSISTANT_MISSING' };
      const finalUnit = leafUnits[leafUnits.length - 1];
      const text = normalize(finalUnit.innerText || finalUnit.textContent || '');
      if (!text) return { ok: false, error: 'RELAY_RECOVERY_DIRECT_ASSISTANT_EMPTY' };
      const completeState = turnState === 'complete';
      const completionUiReady = !!turn.querySelector(
        'button[data-testid="copy-turn-action-button"],button[data-testid*="copy"],button[aria-label="Copy"],button[aria-label="복사"],button[aria-label="복사하기"]'
      );
      if (!completeState && !completionUiReady) {
        return { ok: false, error: 'RELAY_RECOVERY_DIRECT_FINAL_STATE_UNKNOWN' };
      }
      return { ok: true, reply: text };
    }
  });
  const result = injected?.[0]?.result || null;
  if (!result?.ok || !String(result.reply || '').trim()) {
    throw new Error(String(result?.error || 'RELAY_RECOVERY_DIRECT_FAILED'));
  }
  return { ok: true, recovered: true, recoveredReply: String(result.reply || ''), directDom: true };
}

function bindingLeaseTargetsConflict(lease, target) {
  if (!lease || !target) return false;
  return (!!target.role && String(lease.role || '') === String(target.role || ''))
    || (Number(target.tabId || 0) > 0 && Number(lease.tabId || 0) === Number(target.tabId || 0))
    || (!!target.conversationKey
      && String(lease.conversationKey || '') === String(target.conversationKey || ''));
}

function pruneExpiredBindingSubmitLeases(state, now = Date.now()) {
  const leases = state.bindingSubmitLeases || {};
  let changed = false;
  for (const [leaseId, lease] of Object.entries(leases)) {
    if (Number(lease?.expiresAt || 0) <= now) {
      delete leases[leaseId];
      changed = true;
    }
  }
  state.bindingSubmitLeases = leases;
  return changed;
}

function withBindingLeaseMutation(work) {
  const next = bindingLeaseMutationChain.catch(() => {}).then(work);
  bindingLeaseMutationChain = next.catch(() => {});
  return next;
}

async function mutateRegistrationsWithLeaseFence(targets, mutation) {
  return withBindingLeaseMutation(async () => {
    const state = await loadState();
    pruneExpiredBindingSubmitLeases(state);
    const targetList = (Array.isArray(targets) ? targets : [targets]).filter(Boolean);
    const conflict = Object.values(state.bindingSubmitLeases || {}).some((lease) =>
      targetList.some((target) => bindingLeaseTargetsConflict(lease, target)));
    if (conflict) throw new Error('PRE_SUBMIT_BINDING_LEASE_ACTIVE');
    const result = await mutation(state);
    await stateRepository.setLocal({
      registrations: state.registrations,
      [BINDING_SUBMIT_LEASES_KEY]: state.bindingSubmitLeases || {}
    });
    return result;
  });
}

async function resolveExactConversationCommand(message) {
  const conversationKey = String(message?.conversationKey || '').trim();
  const instanceId = String(message?.instanceId || '').trim();
  const sessionId = String(message?.sessionId || '').trim();
  const tabId = Number(message?.tabId);
  if (!/^[a-z0-9-]{8,64}$/i.test(conversationKey)) {
    throw new Error('CONVERSATION_BIND_KEY_INVALID');
  }
  if (!Number.isSafeInteger(tabId) || tabId <= 0) {
    throw new Error('CONVERSATION_BIND_TAB_INVALID');
  }
  const state = await loadState();
  if (instanceId !== String(state.settings?.instanceId || '')) {
    throw new Error('CONVERSATION_BIND_INSTANCE_MISMATCH');
  }
  if (sessionId !== String(endpointSessionId || '')) {
    throw new Error('CONVERSATION_BIND_SESSION_MISMATCH');
  }
  const tab = await browserGateway.getExactTab(tabId);
  if (!isChatTab(tab)
      || RelayCore.conversationKey(String(tab.url || '')) !== conversationKey) {
    throw new Error('CONVERSATION_BIND_TARGET_MISMATCH');
  }
  return tab;
}

async function bindExactConversation(message) {
  const role = RelayCore.normalizeRole(message?.to);
  const tab = await resolveExactConversationCommand(message);
  const conversationKey = String(message?.conversationKey || '').trim();
  const bindingReceiptId = String(message?.bindingReceiptId || '').trim();
  if (!/^RCB-[A-Z0-9]{12,40}$/.test(bindingReceiptId)) {
    throw new Error('CONVERSATION_BINDING_RECEIPT_REQUIRED');
  }
  const registration = await mutateRegistrationsWithLeaseFence(
    [{ role }, { tabId: tab.id, conversationKey }],
    async (state) => {
      const current = state.registrations?.[role] || null;
      if (current) {
        const conflict = Object.values(state.bindingSubmitLeases || {}).some((lease) =>
          bindingLeaseTargetsConflict(lease, current));
        if (conflict) throw new Error('PRE_SUBMIT_BINDING_LEASE_ACTIVE');
      }
      const promotingBootstrap = !!current
        && current.authorization === 'ACT_CONVERSATION_BOOTSTRAP'
        && !String(current.conversationKey || '')
        && Number(current.tabId) === Number(tab.id)
        && String(current.transportInstanceId || '') === String(state.settings.instanceId || '')
        && String(current.sessionId || '') === String(endpointSessionId || '');
      const changingEndpoint = !!current
        && (String(current.conversationKey || '') !== conversationKey
          || Number(current.tabId) !== Number(tab.id));
      if (changingEndpoint && !promotingBootstrap) {
        if (message.replaceStale !== true) throw new Error('LOGICAL_NODE_BINDING_CONFLICT');
        if (String(message.expectedCurrentConversationKey || '') !== String(current.conversationKey || '')
            || String(message.expectedCurrentBindingReceiptId || '') !== String(current.bindingReceiptId || '')) {
          throw new Error('LOGICAL_NODE_BINDING_REPLACEMENT_FENCE_MISMATCH');
        }
      }
      for (const [otherRole, other] of Object.entries(state.registrations || {})) {
        if (otherRole !== role
            && (String(other?.conversationKey || '') === conversationKey
              || Number(other?.tabId) === Number(tab.id))) {
          throw new Error('CONVERSATION_ALREADY_BOUND');
        }
      }
      const next = {
        ...(current || {}), role, tabId: Number(tab.id), conversationKey,
        title: tab.title || current?.title || '',
        transportInstanceId: String(state.settings.instanceId || ''),
        sessionId: String(endpointSessionId || ''), bindingReceiptId,
        authorization: 'ACT_CONVERSATION_BIND', updatedAt: Date.now()
      };
      state.registrations[role] = next;
      return { ...next };
    }
  );
  return {
    ok: true,
    registration,
    binding: {
      logicalNode: role,
      conversationKey,
      instanceId: registration.transportInstanceId,
      sessionId: registration.sessionId,
      tabId: Number(tab.id),
      bindingReceiptId
    }
  };
}

async function resolveRegistration(roleValue) {

  const role = RelayCore.normalizeRole(roleValue);

  const state = await loadState();

  const reg = state.registrations[role];

  if (!reg) throw new Error(`Role not registered: ${role}`);

  if (reg.tabId) {

    try {

      const tab = await browserGateway.getExactTab(reg.tabId);

      if (tab.url && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(tab.url)) {

        const currentKey = RelayCore.conversationKey(tab.url);

        if (reg.conversationKey && currentKey && currentKey !== reg.conversationKey) {

          throw new Error(`Registered conversation changed for ${role}`);

        }

        return reg;

      }

    } catch {}

  }

  const tabs = await getChatTabs();

  const match = tabs.find((tab) => RelayCore.conversationKey(tab.url || '') === reg.conversationKey);

  if (!match) throw new Error(`Registered tab is not open: ${role}`);

  return mutateRegistrationsWithLeaseFence(
    [{ role }, reg, { tabId: match.id, conversationKey: reg.conversationKey }],
    async (latest) => {
      const current = latest.registrations?.[role];
      if (!current || String(current.conversationKey || '') !== String(reg.conversationKey || '')) {
        throw new Error(`Registered conversation changed for ${role}`);
      }
      current.tabId = match.id;
      current.title = match.title || current.title;
      current.updatedAt = Date.now();
      latest.registrations[role] = current;
      return { ...current };
    }
  );

}
