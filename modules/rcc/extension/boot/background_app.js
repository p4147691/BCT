async function connectNativeHost() {
  return nativeTransport.connect();

}

async function handleNativeConnected(connection) {
  const state = await loadState();
  postNative({ type: 'host:ready', extensionId: connection.extensionId,
    instanceId: state.settings.instanceId });
  (async () => {
    const tabs = (await getChatTabs()).filter(isChatTab);
    await ensureRelayReceivers(tabs);
    const endpoints = await publishEndpointSnapshot('native-connect', tabs);
    for (const endpoint of endpoints) {
      if (!endpoint.generating
          && typeof resumeWaitingDeliveriesForEndpoint === 'function') {
        await resumeWaitingDeliveriesForEndpoint(endpoint);
      }
    }
  })().catch(() => {});
}


const RccBackgroundApp = Object.freeze({
  start() {
    nativeTransport = RccNativeTransport.create(chrome, {
      hostName: NATIVE_HOST,
      reconnectDelayMs: 3000,
      onMessage: handleNativeCommand,
      onConnected: handleNativeConnected,
    });
    lifecycle.registerRuntimeMessage(handleRuntimeMessage);
    lifecycle.registerStartup(() => connectNativeHost());
    observationGateway.registerTabListeners({
      onCreated: (tab) => { handleEndpointTabCreated(tab).catch(() => {}); },
      onUpdated: (tabId, changeInfo, tab) => {
        handleEndpointTabUpdated(tabId, changeInfo, tab).catch(() => {});
      },
      onRemoved: (tabId) => { handleEndpointTabRemoved(tabId).catch(() => {}); },
      onMoved: (tabId) => { handleEndpointTabMoved(tabId).catch(() => {}); },
    });
    connectNativeHost();
  },
});
