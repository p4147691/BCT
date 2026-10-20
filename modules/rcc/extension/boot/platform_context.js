const CHAT_URLS = ['https://chatgpt.com/*', 'https://chat.openai.com/*'];
const RCC_CONTENT_FILES = [
  'relay_core.js',
  'content/conversation_dom.js',
  'content/simple_relay_executor.js',
  'content/content_router.js',
  'content/activity_reporter.js',
  'content.js',
];
const stateRepository = RccChromeStateRepository.create(chrome, () => crypto.randomUUID());
const browserGateway = RccBrowserGateway.create(chrome, {
  chatUrls: CHAT_URLS,
  receiverFiles: RCC_CONTENT_FILES,
});
const observationGateway = RccObservationGateway.create(chrome);
const lifecycle = RccLifecycle.create(chrome);

const NATIVE_HOST = 'com.ai_workspace_relay.host';
const RCC_BACKGROUND_BUILD_ID = '2026-10-20-rcc-core-shadow-v1';
let nativeTransport = null;
