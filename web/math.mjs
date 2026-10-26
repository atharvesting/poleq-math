import MarkdownIt from 'markdown-it';
import texmath from 'markdown-it-texmath';
import katex from 'katex';

// Accept the spaces Ollama often adds inside $ delimiters; keep the plugin's escape/currency guards.
texmath.rules.dollars.inline.find(rule => rule.tag === '$').rex = /\$((?:\\.|[^\\$\n])+)\$/gy;
export const options = {throwOnError: true, trust: false, maxExpand: 1000, maxSize: 20, strict: 'error'};
export const markdown = new MarkdownIt({html: false, linkify: false}).use(texmath, {
  engine: katex, delimiters: ['dollars', 'brackets'], katexOptions: options
});
export function validateMath(body, latex = '') {
  const errors = [];
  const check = (source, displayMode) => {
    try { katex.renderToString(source, {...options, displayMode, macros: {}}); }
    catch (e) { errors.push(e.message); }
  };
  if (latex) check(latex, true);
  const visit = tokens => {
    for (const token of tokens) {
      if (token.type.startsWith('math_')) check(token.content, token.type.includes('block'));
      if (token.children) visit(token.children);
    }
  };
  visit(markdown.parse(body, {}));
  return errors;
}
export function formula(latex) { return katex.renderToString(latex, {...options, displayMode: true, macros: {}}); }

// A display formula becomes one row per clause. `,\quad`, `\qquad` and `;` always
// break; a bare comma breaks only when both sides read as clauses (they carry a
// relation or a multi-word \text), so lists such as \lambda_1,\dots,\lambda_n stay
// on one line. Tuples, sets, \left…\right groups and environments stay atomic.
const SPACING = /^(?:\\quad|\\qquad|\\,|\\;|\\:|\\ )+/;
const RELATION = /(?:[=<>]|\\(?:le|leq|ge|geq|ne|neq|approx|equiv|implies|iff|in|notin|subset|subseteq|to|mapsto|sim|perp|parallel|mid|triangleq)(?![a-zA-Z]))/;
const SPOKEN = /\\text\{[^{}]*\s[^{}]*\}/;
const clause = piece => RELATION.test(piece) || SPOKEN.test(piece);
function environmentEnd(latex, start) {
  let depth = 0, i = start;
  while (i < latex.length) {
    const open = latex.indexOf('\\begin', i), close = latex.indexOf('\\end', i);
    if (close < 0) return i + 1;
    if (open >= 0 && open < close) { depth++; i = open + 6; }
    else { depth--; i = latex.indexOf('}', close) + 1 || latex.length; if (!depth) return i; }
  }
  return latex.length;
}
export function wrapMath(latex) {
  if (!latex) return null;
  const chunks = [];
  let start = 0, pending = {join: '', strong: false};
  let brace = 0, bracket = 0, paren = 0, left = 0;
  const top = () => brace <= 0 && bracket <= 0 && paren <= 0 && left <= 0;
  const cut = (end, join, strong, resume = end) => {
    const text = latex.slice(start, end).trim();
    if (text) chunks.push({text, ...pending}); else pending.strong ||= strong;
    pending = {join, strong};
    start = resume;
  };
  for (let i = 0; i < latex.length; i++) {
    const c = latex[i];
    if (c === '\\') {
      const command = /^\\([a-zA-Z]+)/.exec(latex.slice(i));
      if (!command) {
        const next = latex[i + 1];
        if (next === '{') brace++; else if (next === '}') brace--;
        i++; continue;
      }
      const name = command[1];
      if (name === 'begin') { i = environmentEnd(latex, i) - 1; continue; }
      if (name === 'left') left++;
      else if (name === 'right') left = Math.max(0, left - 1);
      else if (top() && (name === 'quad' || name === 'qquad')) {
        const text = latex.slice(start, i).trim();
        if (text) { chunks.push({text, ...pending}); pending = {join: '\\quad ', strong: false}; }
        start = i + command[0].length;
        i += command[0].length - 1; continue;
      }
      i += command[0].length - 1; continue;
    }
    if (c === '{') brace++;
    else if (c === '}') brace--;
    else if (c === '[') bracket++;
    else if (c === ']') bracket--;
    else if (c === '(') paren++;
    else if (c === ')') paren--;
    else if (c === ',' && top()) cut(i, ',', /^\s*\\(?:qquad|quad)(?![a-zA-Z])/.test(latex.slice(i + 1)), i + 1);
    else if (c === ';' && top()) cut(i, ';', true, i + 1);
  }
  const tail = latex.slice(start).trim().replace(SPACING, '').trim();
  if (tail) chunks.push({text: tail, ...pending});
  const rows = [];
  for (const chunk of chunks) {
    const text = chunk.text.replace(SPACING, '').trim();
    if (!text) continue;
    const last = rows.length - 1;
    if (last < 0 || chunk.strong || (clause(rows[last]) && clause(text))) rows.push(text);
    else rows[last] += chunk.join + text;
  }
  if (rows.length < 2) return null;
  // gathered centres every row and keeps display-style limits, unlike array{l}.
  return `\\begin{gathered}${rows.join(' \\\\ ')}\\end{gathered}`;
}
