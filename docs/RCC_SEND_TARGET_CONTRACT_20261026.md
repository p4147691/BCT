# RCC command contract

- send requires to and text; tab_id and target are not aliases. Legacy broad RCC instance claim remains unchanged.
- send-to-tab requires session_id (32 hex), tab_id, window_id, text, optional conversation_key (UUID). Use fresh exact identity checks before any existing-tab send. Resource scope: direct-tab.
- delivery-start requires delivery_id, manager_conversation_key, worker_conversation_key, text and optional scope_id. Resource scope: delivery ID.
- Do not retry UNKNOWN, release FINISHED/UNKNOWN claims without proof, or modify legacy send semantics.
- No new transport or live delivery.
