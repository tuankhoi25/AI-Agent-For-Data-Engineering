export const fixture = {
  title: 'Synthetic view', description: 'Synthetic observations in test units, line grain; filters operate on supplied rows.', height: 480,
  table: { name: 'observations', schema: { Day: 'string', Category: 'string', Revenue: 'float', Units: 'integer' }, rows: [
    { Day: '2026-09-01', Category: 'Bakery', Revenue: '100', Units: '2' },
    { Day: '2026-09-02', Category: 'Bakery', Revenue: '200', Units: '4' },
    { Day: '2026-09-01', Category: 'Beverage', Revenue: '40', Units: '1' },
    { Day: '2026-09-02', Category: 'Beverage', Revenue: '60', Units: '2' },
  ] },
  view: { plugin: 'Y Line', columns: ['Revenue'], group_by: ['Day'], aggregates: { Revenue: 'sum' }, sort: [['Day', 'asc']] },
};
export const toolEvents = (id, name, args) => [
  { type: 'TEXT_MESSAGE_START', messageId: `${id}-message`, role: 'assistant' },
  { type: 'TOOL_CALL_START', toolCallId: id, toolCallName: name, parentMessageId: `${id}-message` },
  { type: 'TOOL_CALL_ARGS', toolCallId: id, delta: JSON.stringify(args) },
  { type: 'TOOL_CALL_END', toolCallId: id },
  { type: 'TEXT_MESSAGE_END', messageId: `${id}-message` },
];
export const textEvents = (id, text) => [
  { type: 'TEXT_MESSAGE_START', messageId: id, role: 'assistant' },
  { type: 'TEXT_MESSAGE_CONTENT', messageId: id, delta: text },
  { type: 'TEXT_MESSAGE_END', messageId: id },
];
export const reply = (route, input, events) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: [
  { type: 'RUN_STARTED', threadId: input.threadId, runId: input.runId }, ...events,
  { type: 'RUN_FINISHED', threadId: input.threadId, runId: input.runId },
].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
