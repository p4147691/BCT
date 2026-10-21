// The manifest loads these content modules in dependency order before this assembly guard.
if ([executeSimpleRelayV0, readSimpleRelayV0Reply, executeNewChatBootstrap,
  readNewChatBootstrapStatus, reportGenerationSignal].some((item) => typeof item !== 'function'))
  throw new Error('RCC_CONTENT_ASSEMBLY_INCOMPLETE');
