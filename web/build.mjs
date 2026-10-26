import {build} from 'esbuild';
import {createHash} from 'node:crypto';
import {mkdir, cp, copyFile, readFile, writeFile} from 'node:fs/promises';
const dest = 'src/poleq/static';
await mkdir(dest, {recursive: true});
await build({entryPoints: ['web/app.jsx'], bundle: true, minify: true, format: 'esm', define: {'process.env.NODE_ENV':'"production"'}, outfile: `${dest}/app.js`});
await build({entryPoints: ['web/validate.mjs'], bundle: true, minify: true, platform: 'node', format: 'cjs', outfile: `${dest}/validate.cjs`});
await copyFile('web/style.css', `${dest}/style.css`);
await copyFile('web/favicon.svg', `${dest}/favicon.svg`);
let html=await readFile('web/index.html','utf8');
for (const name of ['app.js','style.css']) {
  const hash=createHash('sha256').update(await readFile(`${dest}/${name}`)).digest('hex').slice(0,12);
  html=html.replace(`/static/${name}`,`/static/${name}?v=${hash}`);
}
await writeFile(`${dest}/index.html`,html);
await copyFile('node_modules/katex/dist/katex.min.css', `${dest}/katex.min.css`);
await copyFile('node_modules/@blueprintjs/core/lib/css/blueprint.css', `${dest}/blueprint.css`);
await cp('node_modules/katex/dist/fonts', `${dest}/fonts`, {recursive: true});
let licenses = '';
for (const pkg of ['react','react-dom','@blueprintjs/core','@blueprintjs/icons','d3-force','d3-quadtree','d3-timer','d3-dispatch','katex', 'cytoscape', 'markdown-it', 'markdown-it-texmath', 'dompurify']) {
  const p = JSON.parse(await readFile(`node_modules/${pkg}/package.json`, 'utf8'));
  let license = '';
  for (const filename of ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'license.txt']) {
    try { license = await readFile(`node_modules/${pkg}/${filename}`, 'utf8'); break; } catch {}
  }
  licenses += `\n## ${pkg} ${p.version} (${p.license})\n${license}\n`;
}
await writeFile(`${dest}/THIRD_PARTY_LICENSES.txt`, licenses);
