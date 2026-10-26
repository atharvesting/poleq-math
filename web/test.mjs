import assert from 'node:assert/strict';
import {validateMath,markdown,formula,wrapMath} from './math.mjs';
assert.deepEqual(validateMath('A square matrix $A^{\\mathsf{T}}=-A$.','n\\text{ odd}\\implies\\det(A)=0'),[]);
assert.deepEqual(validateMath('Display: $$\\frac{x}{2}$$ and brackets \\(x^2\\).'),[]);
assert.equal(validateMath('Bad $\\notACommand$').length,1);
assert.equal(validateMath('', '\\frac{x}').length,1);
assert.ok(markdown.render('**Definition** with $x^2$').includes('katex'));
assert.ok(markdown.render('Odd order $ n $ means $ n=2k+1 $.').includes('katex'));
assert.equal(validateMath('Bad $ \\notACommand $').length,1);
assert.ok(!markdown.render('`$ n $` and \\$ n \\$').includes('katex'));
assert.ok(!markdown.render('Costs $5 and $10.').includes('katex'));
assert.ok(!markdown.render('<script>alert(1)</script>').includes('<script>'));
assert.ok(!formula('\\href{https://example.com}{x}').includes('href='));
console.log('Math parsing, syntax checks and HTML safety: passed');

// Line breaking must respect nesting, must not fragment lists, and must never invent invalid LaTeX.
assert.equal(wrapMath('A=B'),null);
assert.equal(wrapMath('A=B,\\quad C=D'),'\\begin{gathered}A=B \\\\ C=D\\end{gathered}');
assert.equal(wrapMath('\\text{a, b},\\quad c'),'\\begin{gathered}\\text{a, b} \\\\ c\\end{gathered}');
assert.equal(wrapMath('f(x,y),\\quad z'),'\\begin{gathered}f(x,y) \\\\ z\\end{gathered}');
assert.equal(wrapMath('\\{a,b\\}'),null,'Commas inside a set stay put');
assert.equal(wrapMath('A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}'),null,'A lone matrix has no separator');
assert.equal(wrapMath('\\begin{aligned}a&=b\\\\c&=d\\end{aligned}'),null,'An authored block is left alone');
assert.equal(wrapMath('A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix},\\quad B=C'),'\\begin{gathered}A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix} \\\\ B=C\\end{gathered}','Commas inside a matrix are skipped, the outer clause breaks');
assert.equal(wrapMath('x=1,\\quad y=2,\\quad z=3'),'\\begin{gathered}x=1 \\\\ y=2 \\\\ z=3\\end{gathered}');
assert.equal(wrapMath('\\lambda_1,\\lambda_2,\\dots,\\lambda_n'),null,'A comma-separated list stays on one line');
assert.equal(wrapMath('a_1, a_2, a_3'),null);
assert.equal(wrapMath('x>0, y<1'),'\\begin{gathered}x>0 \\\\ y<1\\end{gathered}','A bare comma between clauses still breaks');
assert.equal(wrapMath('n\\text{ odd}, n\\text{ prime}'),'\\begin{gathered}n\\text{ odd} \\\\ n\\text{ prime}\\end{gathered}');
assert.equal(wrapMath('x=1; y=2'),'\\begin{gathered}x=1 \\\\ y=2\\end{gathered}');
assert.ok(formula(wrapMath('A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix},\\quad B=C')).includes('katex'),'A nested matrix still renders');
assert.ok(formula(wrapMath('\\begin{aligned}a&=b\\\\c&=d\\end{aligned},\\quad x=1')).includes('katex'),'A nested authored block still renders');
assert.ok(formula(wrapMath('x=1,\\quad y=2,\\quad z=3')).includes('katex'),'Wrapped output must render');
console.log('Semantic formula line breaking: passed');

// Exercise real forces and Cytoscape drag events, including viewport preservation.
const {default:cytoscape} = await import('cytoscape');
const {graphPhysics} = await import('./graph.mjs');
function makeGraph() {
  return cytoscape({headless:true,layout:{name:'preset'},elements:[
    ...['a','b','c'].map((id,i)=>({data:{id},position:{x:i*200,y:i%2*150}})),
    {data:{id:'ab',source:'a',target:'b'}}
  ]});
}
function positions(gravity) {
  const cy=makeGraph(), physics=graphPhysics(cy,gravity);
  physics.simulation.stop().tick(150);
  const points=physics.simulation.nodes().map(n=>({x:n.x,y:n.y}));
  physics.destroy();cy.destroy();
  assert.ok(points.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
  return points;
}
assert.notDeepEqual(positions(0),positions(10));
const cy=makeGraph(), physics=graphPhysics(cy,4), node=cy.getElementById('a');
physics.simulation.stop();
assert.deepEqual(Object.keys(node.position()).sort(),['x','y'],'Renderer positions must contain coordinates only');
const beforeClick=physics.simulation.alpha();
node.emit('grab');node.emit('free');physics.simulation.stop();
assert.equal(physics.simulation.alpha(),beforeClick,'Selecting a node must not reheat the graph');
cy.zoom(1.3);cy.pan({x:35,y:70});
const viewport={zoom:cy.zoom(),pan:{...cy.pan()}};
node.emit('grab');
const dropped={x:node.position().x+180,y:node.position().y+90};
node.position(dropped);node.emit('drag');
physics.simulation.stop();
const dragAlpha=physics.simulation.alpha();
node.emit('drag');physics.simulation.stop();
assert.equal(physics.simulation.alpha(),dragAlpha,'Mouse movement must not restart the simulation');
physics.simulation.tick(20);
const point=physics.simulation.nodes().find(n=>n.id==='a');
assert.equal(point.x,dropped.x);assert.equal(point.y,dropped.y);
node.emit('free');physics.simulation.stop();
assert.equal(point.x,dropped.x);assert.equal(point.y,dropped.y);
assert.equal(point.fx,null);assert.equal(point.fy,null);
physics.simulation.tick();physics.simulation.on('tick')();
assert.ok(Math.hypot(point.x-dropped.x,point.y-dropped.y)<30,'Release should continue smoothly, not reset the layout');
const beforeGravity=physics.simulation.nodes().map(n=>({x:n.x,y:n.y}));
physics.setGravity(8);physics.simulation.stop();
assert.deepEqual(physics.simulation.nodes().map(n=>({x:n.x,y:n.y})),beforeGravity,'Changing gravity must not replace current positions');
physics.simulation.tick(100);physics.simulation.on('tick')();
assert.deepEqual({zoom:cy.zoom(),pan:cy.pan()},viewport);
assert.ok(physics.simulation.nodes().every(n=>Number.isFinite(n.x)&&Number.isFinite(n.y)));
physics.destroy();cy.destroy();
console.log('Graph gravity, dragging without reset, finite positions and viewport preservation: passed');

// A domain-only view has one node: dropping it must not pull it to its old origin.
for (const reducedMotion of [false,true]) {
  const single=cytoscape({headless:true,layout:{name:'preset'},elements:[{data:{id:'only'},position:{x:0,y:0}}]});
  const force=graphPhysics(single,10,reducedMotion), moved=single.getElementById('only');
  let synchronousSteps=0;
  const tick=force.simulation.tick;
  force.simulation.tick=(n=1)=>{synchronousSteps+=n;return tick(n);};
  moved.emit('grab');moved.position({x:180,y:90});moved.emit('drag');moved.emit('free');force.simulation.stop();
  assert.equal(synchronousSteps,0,'Dragging must not run synchronous settling loops');
  force.simulation.tick(300);force.simulation.on('tick')();
  assert.deepEqual(moved.position(),{x:180,y:90},'A drop must not restore the old graph origin');
  force.destroy();single.destroy();
}
console.log('Drag origin and reduced-motion regression checks: passed');

// Compare slider changes on an already settled graph, rather than separate initial layouts.
function spreadAfterChange(gravity) {
  const cy=makeGraph(), force=graphPhysics(cy,4);
  force.setGravity(gravity);force.simulation.stop().tick(300);
  const nodes=force.simulation.nodes(), x=nodes.reduce((sum,n)=>sum+n.x,0)/nodes.length, y=nodes.reduce((sum,n)=>sum+n.y,0)/nodes.length;
  const radius=Math.sqrt(nodes.reduce((sum,n)=>sum+(n.x-x)**2+(n.y-y)**2,0)/nodes.length);
  force.destroy();cy.destroy();return radius;
}
const loose=spreadAfterChange(0), compact=spreadAfterChange(10);
assert.ok(compact<loose*0.8,`Gravity changes should noticeably alter spread: 0=${loose}, 10=${compact}`);
console.log('Visible gravity range on an existing graph: passed');
