// The manifest loads these content modules in dependency order before this assembly guard.
if ([executeSimpleRelayV0, readSimpleRelayV0Reply, executeOrchestrationContent,
  recoverOrchestrationContent, executeNewChatBootstrap,
  readNewChatBootstrapStatus, reportGenerationSignal].some((item) => typeof item !== 'function'))
  throw new Error('RCC_CONTENT_ASSEMBLY_INCOMPLETE');

setTimeout(() => { recoverOrchestrationContent().catch(() => {}); }, 0);
