// The app definition is JSON with IML expressions, so the checks are structural: every file parses,
// every code file the manifest names exists, every module has a label, a description, an interface
// that matches its sample, the connection sanitizes the key, and the search module paginates on the
// API's next_cursor with a limit. No request is made.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const root = new URL('../src/', import.meta.url).pathname;
const read = (p) => JSON.parse(readFileSync(join(root, p), 'utf8'));
const app = read('makecomapp.json');

for (const file of Object.values(app.generalCodeFiles)) assert.ok(existsSync(join(root, file)), file);

const base = read(app.generalCodeFiles.base);
assert.equal(base.baseUrl, 'https://api.faxforagents.com');
assert.match(base.headers.authorization, /^Bearer \{\{connection\.apiKey\}\}$/);
assert.deepEqual(base.log.sanitize, ['request.headers.authorization']);
assert.ok(base.response.error.message.includes('error_code'), 'the error message carries the stable code');

const [connName, conn] = Object.entries(app.components.connection)[0];
assert.equal(connName, 'faxforagents');
const connApi = read(conn.codeFiles.communication);
assert.equal(connApi.url, 'https://api.faxforagents.com/v1/me');
assert.deepEqual(connApi.log.sanitize, ['request.headers.authorization']);
const [param] = read(conn.codeFiles.params);
assert.deepEqual([param.name, param.type, param.required], ['apiKey', 'password', true]);

const groups = read(app.generalCodeFiles.groups).flatMap((g) => g.modules);
for (const [name, mod] of Object.entries(app.components.module)) {
  assert.ok(mod.label && mod.description, `${name} has a label and a description`);
  assert.equal(mod.connection, 'faxforagents');
  assert.ok(groups.includes(name), `${name} is in a group`);
  for (const file of Object.values(mod.codeFiles)) assert.ok(existsSync(join(root, file)), file);
  const iface = read(mod.codeFiles.interface);
  const sample = read(mod.codeFiles.samples);
  for (const field of iface) assert.ok(field.name in sample, `${name}: sample has ${field.name}`);
}

const send = read(app.components.module.sendFax.codeFiles.communication);
assert.deepEqual(send.map((r) => [r.method, r.url]), [['POST', '/v1/documents'], ['POST', '/v1/fax-quotes'], ['POST', '/v1/faxes']]);
assert.ok(send[1].response.valid.condition.includes('authorization_required'), 'a quote that needs approval stops the module');
assert.match(send[2].headers['idempotency-key'], /temp\.quoteId/);

const list = read(app.components.module.listInbox.codeFiles.communication);
assert.equal(list.response.iterate, '{{body.items}}');
assert.equal(list.response.limit, '{{parameters.limit}}');
assert.equal(list.pagination.qs.cursor, '{{body.next_cursor}}');
assert.equal(list.pagination.condition, '{{body.next_cursor}}');
assert.ok(read(app.components.module.listInbox.codeFiles.mappableParams).some((p) => p.name === 'limit' && p.required));

assert.equal(app.components.module.universal.moduleType, 'universal');

// The icon Make shows: a PNG, square, 512 px or more (Make's app logo requirements).
const icon = readFileSync(join(root, 'assets/icon.png'));
assert.equal(icon.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', 'assets/icon.png is a PNG');
const [w, h] = [icon.readUInt32BE(16), icon.readUInt32BE(20)];
assert.ok(w === h && w >= 512, `icon is square and at least 512 px (${w}x${h})`);
for (const origin of app.origins) assert.match(origin.appId, /^[a-z][0-9a-z-]+[0-9a-z]$/, 'origin appId is a Make app id');
console.log('make app definition ok:', Object.keys(app.components.module).join(', '));
