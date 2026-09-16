import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const input = await readFile(new URL('../frontend/src/rtlDiagnostics.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(input, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { rtlDiagnostics, sourceMapping, diagnosticLinkProblem } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const record = log => ({ command: [], exit_code: 1, error: null, log });
const records = {
  lint: record("%Error: design.sv:2:14: Can't find definition of variable: 'missing'\n%Error: Exiting due to 1 error(s)\n  2 | %Error: design.sv:999:1: source excerpt"),
  width: record('%Warning-WIDTHTRUNC: ./design.sv:3:8: width mismatch'),
  synthesize: record("design.sv:2: Warning: Identifier `\\missing' is implicitly declared.\ndesign.sv:4: ERROR: syntax error\nWarning: wire design.sv:5 has no driver"),
};
const parsed = rtlDiagnostics(records);
assert.equal(parsed.items.length, 4);
assert.equal(parsed.items[0].line, 2);
assert.equal(parsed.items[0].column, 14);
assert.equal(parsed.items[1].code, 'WIDTHTRUNC');
assert.equal(parsed.items[3].column, null);
assert.equal(parsed.items[3].severity, 'ERROR');
const mapping = sourceMapping('one\ntwo\nthree\nfour\n');
assert.equal(mapping.lines.length, 4);
assert.equal(sourceMapping('').lines.length, 0);
for (const item of parsed.items) assert.equal(diagnosticLinkProblem(item, mapping), null);
for (const file of ['/tmp/design.sv', '../design.sv', 'testbench.sv', 'https://example.com/design.sv']) {
  assert.ok(diagnosticLinkProblem({ ...parsed.items[0], file }, mapping));
}
for (const line of [0, -1, 5, Number.MAX_SAFE_INTEGER + 1, Infinity]) {
  assert.ok(diagnosticLinkProblem({ ...parsed.items[0], line }, mapping));
}
assert.ok(diagnosticLinkProblem(parsed.items[0], sourceMapping(null)));
assert.ok(diagnosticLinkProblem(parsed.items[0], sourceMapping('`line 2 "design.sv" 0\na\nb')));
assert.equal(sourceMapping('a\r\nb\r\n').lines.length, 2);
assert.deepEqual(rtlDiagnostics(undefined), { items: [], truncated: false });
assert.equal(rtlDiagnostics({lint: record(Array(220).fill('%Error: design.sv:2:1: bad').join('\n'))}).items.length, 200);
assert.ok(rtlDiagnostics({lint: record(Array(220).fill('%Error: design.sv:2:1: bad').join('\n'))}).truncated);
assert.ok(rtlDiagnostics({lint: record('x'.repeat(131073))}).truncated);
console.log('PASS: real diagnostic formats, source excerpt exclusion, file/range/remap guards, CRLF, missing logs and display limits');
