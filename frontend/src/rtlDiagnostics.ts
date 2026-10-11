import type { RtlSignoffResult } from './api';
import { tr } from './components/LanguageProvider';

export type RtlDiagnostic = {
  tool: 'lint' | 'width' | 'synthesize'; severity: string; code: string | null;
  file: string; line: number; column: number | null; message: string;
};

// Only explicit location-bearing diagnostic headers, never source excerpts or
// arbitrary references embedded in messages. Keep original tool logs untouched.
export function rtlDiagnostics(records: RtlSignoffResult['tool_runs']) {
  const items: RtlDiagnostic[] = [];
  let truncated = false;
  for (const tool of ['lint', 'width', 'synthesize'] as const) {
    const log = records?.[tool]?.log;
    if (typeof log !== 'string') continue;
    if (log.length > 128 * 1024) truncated = true;
    for (const text of log.slice(0, 128 * 1024).split('\n')) {
      const match = tool === 'synthesize'
        ? /^(\S+):(\d+): (?:(ERROR|Warning)): (.*)$/.exec(text)
        : /^%(Error|Warning)(?:-([A-Z0-9_]+))?: (\S+):(\d+):(\d+): (.*)$/.exec(text);
      if (!match) continue;
      if (items.length === 200) { truncated = true; continue; }
      items.push(tool === 'synthesize'
        ? { tool, file: match[1], line: Number(match[2]), column: null, severity: match[3], code: null, message: match[4] }
        : { tool, severity: match[1], code: match[2] || null, file: match[3], line: Number(match[4]), column: Number(match[5]), message: match[6] });
    }
  }
  return { items, truncated };
}

export function sourceMapping(source: string | null) {
  // A trailing newline terminates the final source line; it adds no extra line.
  const lines = !source ? [] : source.replace(/\n$/, '').split('\n');
  return { lines, remapped: /`line\b/.test(source ?? '') };
}

export function diagnosticLinkProblem(diagnostic: RtlDiagnostic, mapping: ReturnType<typeof sourceMapping>): string | null {
  if (diagnostic.file !== 'design.sv' && diagnostic.file !== './design.sv') return tr('다른 파일의 진단', 'Diagnostic for another file');
  if (mapping.remapped) return tr('`line 지시문으로 위치가 변경될 수 있음', 'Location may be shifted by a `line directive');
  if (!Number.isSafeInteger(diagnostic.line) || diagnostic.line < 1 || diagnostic.line > mapping.lines.length) return tr('저장된 소스 범위 밖', 'Outside the stored source range');
  return null;
}
