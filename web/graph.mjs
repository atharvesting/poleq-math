import {forceSimulation,forceLink,forceManyBody,forceCollide,forceX,forceY} from 'd3-force';

export function graphPhysics(cy, gravity, reducedMotion = false) {
  const nodes=cy.nodes().map(node=>({id:node.id(),x:node.position('x'),y:node.position('y')}));
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const links=cy.edges().map(edge=>({source:edge.source().id(),target:edge.target().id()}));
  const center=()=>({x:nodes.reduce((sum,n)=>sum+n.x,0)/(nodes.length||1),y:nodes.reduce((sum,n)=>sum+n.y,0)/(nodes.length||1)});
  const origin=center();
  const strength=value=>0.12*(value/10)**2;
  let currentGravity=gravity;
  const simulation=forceSimulation(nodes).stop()
    .force('links',forceLink(links).id(n=>n.id).distance(150).strength(0.15))
    .force('repulsion',forceManyBody().strength(-1100))
    .force('collision',forceCollide(55).strength(0.3))
    .force('x',forceX(origin.x).strength(strength(gravity)))
    .force('y',forceY(origin.y).strength(strength(gravity)))
    .velocityDecay(0.6);
  function paint() {
    cy.nodes().positions(node=>{
      if (node.grabbed()) return false;
      const {x,y}=byId.get(node.id()), old=node.position();
      return Math.abs(x-old.x)+Math.abs(y-old.y)>0.01 ? {x,y} : false;
    });
  }
  function wake(alpha=0.1) {simulation.alpha(Math.max(simulation.alpha(),alpha)).restart();}
  function hold(event) {
    const point=byId.get(event.target.id()), {x,y}=event.target.position();
    Object.assign(point,{x,y,fx:x,fy:y,vx:0,vy:0});
    if (event.type==='drag' && !point.dragged) {
      point.dragged=true;
      if (reducedMotion) simulation.stop();
      else {simulation.alphaTarget(0.04);wake();}
    }
  }
  function release(event) {
    const point=byId.get(event.target.id()), {x,y}=event.target.position();
    Object.assign(point,{x,y,fx:null,fy:null,vx:0,vy:0});
    if (!point.dragged) return;
    point.dragged=false;
    // Keep the new arrangement's center; an old fixed origin pulls the whole graph back.
    const origin=center();
    simulation.force('x').x(origin.x);simulation.force('y').y(origin.y);
    simulation.alphaTarget(0);
    if (!reducedMotion) wake();
  }
  simulation.tick(300);paint();
  simulation.on('tick',paint);
  cy.on('grab drag','node',hold);
  cy.on('free','node',release);
  return {simulation,
    setGravity(value) {
      if (value===currentGravity) return;
      currentGravity=value;
      simulation.force('x').strength(strength(value));simulation.force('y').strength(strength(value));
      if (reducedMotion) {simulation.alpha(0.6).stop().tick(300);paint();}
      else wake(0.6);
    },
    destroy() {simulation.stop();cy.off('grab drag','node',hold);cy.off('free','node',release);}
  };
}
export function graphStyle(palette) {
  return [
    {selector:'node',style:{label:'data(label)','background-color':palette.red,color:palette.text,
      'font-size':12,'text-wrap':'wrap','text-max-width':120,'text-valign':'bottom','text-margin-y':8,width:25,height:25}},
    {selector:'node[entity="domains"]',style:{'background-color':palette.orange,shape:'rectangle',width:30,height:30}},
    {selector:'node[entity="entries"]',style:{'background-color':palette.muted,shape:'diamond',width:18,height:18,'font-size':10}},
    {selector:'edge',style:{'line-color':palette.edge,width:2,'curve-style':'bezier'}},
    {selector:'node:selected',style:{'border-color':palette.orange,'border-width':3}},
    {selector:'edge:selected',style:{'line-color':palette.orange,width:4}}
  ];
}
