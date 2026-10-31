# Task Run official public tool only

- Public command: bct_task_run(work_id, operation_id, arguments, approval_ref=None).
- Delegates exclusively to existing orchestrate dispatch and durable receipts.
- Requires existing session-start, node-sync, valid manager epoch and attachment.
- Uses BCT Work/Operation authorization. Never resend UNKNOWN.
- Chain Run remains unfinished and not registered as an official tool.
- Automatic NEXT TASK continuation is outside this Task Run scope.
