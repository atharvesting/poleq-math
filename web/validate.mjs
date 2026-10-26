import {readFileSync} from 'node:fs';
import {validateMath} from './math.mjs';
try {
  const records = JSON.parse(readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(records.map(r => validateMath(r.body ?? r.definition ?? '', r.latex ?? ''))));
} catch (e) {
  process.stderr.write(e.message);
  process.exitCode = 1;
}
