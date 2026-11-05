// Offline checks for chaining, fail-fast behavior and JSON escaping in Postman scripts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const collection = JSON.parse(fs.readFileSync(path.join(__dirname, 'VR Session Flow - Simulacion.postman_collection.json'), 'utf8'));
const flow = collection.item[0].item;
const variables = new Map(collection.variable.map(v => [v.key, v.value]));
let nextRequest;
let updatedBody;
let checks = 0;
const pm = {
  variables: { get: key => variables.get(key) },
  collectionVariables: { set: (key, value) => variables.set(key, value), unset: key => variables.delete(key) },
  execution: { setNextRequest: value => { nextRequest = value; } },
  request: { body: { update: value => { updatedBody = value; } } },
  test: (_name, fn) => { fn(); checks++; },
  expect: (value, message) => ({ to: {
    eql: expected => assert.deepEqual(value, expected, message),
    get exist() { assert.ok(value !== undefined && value !== null, message); return true; },
    be: { get true() { assert.equal(value, true, message); return true; } },
  } }),
};
function run(item, kind, response = {}, status = 200) {
  pm.response = { code: status, json: () => response, text: () => JSON.stringify(response) };
  if (kind === 'test') for (const e of collection.event) vm.runInNewContext(e.script.exec.join('\n'), { pm, Buffer });
  for (const e of item.event.filter(e => e.listen === kind)) vm.runInNewContext(e.script.exec.join('\n'), { pm, Buffer });
}

assert.equal(flow.length, 7);
for (const group of collection.item) for (const item of group.item) {
  for (const e of item.event) new vm.Script(e.script.exec.join('\n'));
  if (item.request.body) JSON.parse(item.request.body.raw);
}
variables.set('software_username', 'synthetic@example.test');
variables.set('software_password', 'quotes" and \\ and \n');
variables.set('session_id', 'old-session');
run(flow[0], 'prerequest');
assert.equal(variables.has('session_id'), false);
assert.equal(JSON.parse(updatedBody).AuthParameters.PASSWORD, variables.get('software_password'));
const claims = Buffer.from(JSON.stringify({ sub: 'test-sub' })).toString('base64url');
run(flow[0], 'test', { AuthenticationResult: { IdToken: 'header.' + claims + '.signature' } });
assert.equal(variables.get('confirmed_by_sub'), 'test-sub');
run(flow[1], 'test', { version_id: '0.0.1', content_hash: 'test-hash' });
run(flow[2], 'prerequest');
run(flow[2], 'test', { acceptance_token: 'test-acceptance' });
run(flow[3], 'prerequest');
run(flow[3], 'test', { session_id: 'new-session', display_code: '123456', metrics_token: 'test-metrics' });
run(flow[4], 'prerequest');
run(flow[4], 'test', { session_id: 'new-session', status: 'confirmed' });
run(flow[5], 'prerequest');
run(flow[5], 'test', { status: 'completed' });
const metrics = JSON.parse(flow[5].request.body.raw);
assert.equal(Object.keys(metrics).length, 11);
run(flow[6], 'prerequest');
run(flow[6], 'test', { sessions: [{ session_id: 'new-session', status: 'completed', metrics }] });
assert.equal(variables.get('session_status'), 'completed');
assert.throws(() => run(flow[2], 'test', {}, 409));
assert.equal(nextRequest, null);
assert.equal(variables.get('acceptance_token'), 'test-acceptance');
assert.throws(() => run(flow[3], 'test', { session_id: 'incomplete' }), /display_code/);
assert.throws(() => run(flow[0], 'test', { ChallengeName: 'NEW_PASSWORD_REQUIRED' }), /challenge/);
assert.throws(() => run(flow[6], 'test', { sessions: [] }));
const admin = collection.item[1].item[0];
variables.set('admin_id_token', 'admin-test');
variables.set('terms_version', 'test-version');
variables.set('terms', 'Línea "uno"\r\nRuta \\dos\rfinal');
run(admin, 'prerequest');
assert.equal(JSON.parse(updatedBody).content, 'Línea "uno"\nRuta \\dos\nfinal');
assert.equal(JSON.parse(updatedBody).published, false);
assert.equal(collection.variable.find(v => v.key === 'software_password').value, '');
console.log(`OK: ${checks} assertions from Postman tests; full synthetic chain, error stops, Cognito challenge and JSON escaping verified offline.`);
