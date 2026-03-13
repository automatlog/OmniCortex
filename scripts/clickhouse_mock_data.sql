USE omnicortex;

-- ---------------------------------------------------------------------------
-- Mock dataset: 3 linked interactions across UsageLogs + ChatArchive
-- and 3 lifecycle events in AgentLogs.
-- ---------------------------------------------------------------------------

INSERT INTO omnicortex.UsageLogs
(
    Timestamp, RequestId, SessionId, Id, UserId, ProductId,
    ChannelName, ChannelType, Model,
    QueryTokens, PromptTokens, CompletionTokens,
    Latency, HitRate, Cost, Status, Error
)
VALUES
(
    now64(3), 'req-mock-001', 'sess-mock-001',
    toUUID('11111111-1111-1111-1111-111111111111'),
    102, 1, 'TEXT', 'UTILITY', 'llama3.1:8b',
    12, 512, 96,
    1420.35, 1, 0.0012, 'success', ''
),
(
    now64(3), 'req-mock-002', 'sess-mock-001',
    toUUID('11111111-1111-1111-1111-111111111111'),
    102, 1, 'TEXT', 'MARKETING', 'llama3.1:8b',
    18, 640, 121,
    1887.44, 1, 0.0019, 'success', ''
),
(
    now64(3), 'req-mock-003', 'sess-mock-002',
    toUUID('22222222-2222-2222-2222-222222222222'),
    205, 2, 'VOICE', 'AUTHENTICATION', 'llama3.1:8b',
    9, 420, 88,
    1321.07, 0, 0.0011, 'error', 'Temporary upstream timeout'
);

INSERT INTO omnicortex.ChatArchive
(
    Timestamp, Id, UserId, RequestId, Content,
    StartedAt, EndedAt, SessionId, Status, Error
)
VALUES
(
    now64(3),
    toUUID('11111111-1111-1111-1111-111111111111'),
    102, 'req-mock-001',
    '{"user":"Hi, I need product info.","ai":"Sure, I can help with product details."}',
    now64(3) - toIntervalSecond(2), now64(3),
    'sess-mock-001', 'success', ''
),
(
    now64(3),
    toUUID('11111111-1111-1111-1111-111111111111'),
    102, 'req-mock-002',
    '{"user":"Track my order please.","ai":"Your order is in transit and arrives tomorrow."}',
    now64(3) - toIntervalSecond(2), now64(3),
    'sess-mock-001', 'success', ''
),
(
    now64(3),
    toUUID('22222222-2222-2222-2222-222222222222'),
    205, 'req-mock-003',
    '{"user":"I cannot authenticate my account.","ai":"I am escalating this issue to support."}',
    now64(3) - toIntervalSecond(3), now64(3),
    'sess-mock-002', 'error', 'Authentication service unavailable'
);

INSERT INTO omnicortex.AgentLogs
(
    Timestamp, EventId, Id, UserId, Status,
    CreatedAt, DeletedAt, AgentName, ModelSelection, RoleType, SubagentType,
    VectorStore, VectorChunks, ParentChunks, Payload, Error
)
VALUES
(
    now64(3), 'evt-mock-001',
    toUUID('11111111-1111-1111-1111-111111111111'),
    102, 'Active',
    now64(3), NULL,
    'Retail Mock Agent', 'Meta Llama-3.1-8B-Instruct', 'CustomerSupport', 'RetailEcommerce',
    'omni_agent_11111111-1111-1111-1111-111111111111', 690, 109,
    '{"agentType":"BusinessAgent","subagentType":"RetailEcommerce"}',
    ''
),
(
    now64(3), 'evt-mock-002',
    toUUID('11111111-1111-1111-1111-111111111111'),
    102, 'Updated',
    now64(3), NULL,
    'Retail Mock Agent', 'Meta Llama-3.1-8B-Instruct', 'CustomerSupport', 'RetailEcommerce',
    'omni_agent_11111111-1111-1111-1111-111111111111', 742, 121,
    '{"restartAfterUpdate":true}',
    ''
),
(
    now64(3), 'evt-mock-003',
    toUUID('22222222-2222-2222-2222-222222222222'),
    205, 'Deleted',
    now64(3) - toIntervalDay(1), now64(3),
    'Voice Mock Agent', 'Meta Llama-3.1-8B-Instruct', 'TechnicalSupport', 'TechnologySoftware',
    'omni_agent_22222222-2222-2222-2222-222222222222', 410, 78,
    '{"agentDeleted":true}',
    ''
);
