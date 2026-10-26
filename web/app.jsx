import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Button, Checkbox, Dialog, FormGroup, HTMLSelect, InputGroup, Slider, Spinner, TextArea} from '@blueprintjs/core';
import cytoscape from 'cytoscape';
import DOMPurify from 'dompurify';
import {markdown, formula, validateMath, wrapMath} from './math.mjs';
import {graphPhysics, graphStyle} from './graph.mjs';

const kinds = ['property','proof','equivalence','note'];
const staleWindows = {'15':[15,30],'30':[30,45],'45':[45,null]};
function openedLabel(stamp) {
  if (!stamp) return 'never';
  const days = Math.floor((Date.now() - new Date(stamp)) / 86400000);
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;
}
async function api(path, method = 'GET', data) {
  const response = await fetch('/api/' + path, {method,headers:data === undefined ? {} : {'Content-Type':'application/json'},body:data === undefined ? undefined : JSON.stringify(data)});
  const payload = response.status === 204 ? null : response.headers.get('content-type')?.includes('application/json') ? await response.json() : {detail:{message:await response.text()}};
  if (!response.ok) {
    const d = payload.detail;
    const message = Array.isArray(d) ? d.map(x => `${x.loc.join('.')}: ${x.msg}`).join('\n') : [d?.message ?? 'Request failed',...(d?.errors ?? []).map(x => typeof x === 'string' ? x : x.msg)].join('\n');
    const error = new Error(message); error.existingId = d?.existing_id; throw error;
  }
  return payload;
}
function Rich({text = '', math = false, className = ''}) {
  let rendered;
  try { rendered = math ? formula(text) : markdown.render(text); }
  catch (e) { return <p className="error">{e.message}</p>; }
  return <div className={className} dangerouslySetInnerHTML={{__html:DOMPurify.sanitize(rendered)}} />;
}
function WrappedFormula({text, className}) {
  const wrapped = wrapMath(text);
  let rendered;
  try { rendered=formula(wrapped ?? text); }
  catch { try { rendered=formula(text); } catch (e) { return <p className="error">{e.message}</p>; } }
  return <div className={`${className}${wrapped ? ' centered' : ''}`} dangerouslySetInnerHTML={{__html:DOMPurify.sanitize(rendered)}} />;
}
function RecordCard({entity, record, opened, selected, onOpen}) {
  const kind = entity === 'entries' ? record.kind : entity.slice(0,-1);
  const title = record.title ?? record.name;
  const openedNote = entity === 'domains' ? '' : ` · opened ${openedLabel(opened)}`;
  return <article className={`card kind-${kind}${selected ? ' selected' : ''}`} role="button" tabIndex={0}
    data-record={record.id} data-kind={kind} aria-label={`Open ${title}, ${kind}`} title={`${kind}: ${title}${openedNote}`}
    onClick={() => onOpen(entity,record.id)} onKeyDown={e => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault();onOpen(entity,record.id);}}}>
    <h3>{title}</h3>
    {record.latex && <Rich text={record.latex} math className="card-math" />}
    {(record.body ?? record.definition) && <Rich text={record.body ?? record.definition} className="card-body" />}
  </article>;
}
function Graph({catalog,domain,level,focus,setLevel,setFocus,gravity,setGravity,theme,onOpen,onEdge,onError}) {
  const container = useRef(null), cy = useRef(null), physics = useRef(null), gravityRef = useRef(gravity);
  const [result,setResult] = useState(null);
  gravityRef.current = gravity;
  const palette = () => {
    const css = getComputedStyle(document.documentElement);
    return Object.fromEntries(['red','orange','text','muted','edge'].map(key => [key,css.getPropertyValue('--'+key).trim()]));
  };
  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({level}); if(domain) params.set('domain_id',domain); if(focus) params.set('focus',focus);
    setResult(null);
    api('graph?'+params).then(data => {
      if (cancelled) return;
      setResult(data);
      cy.current = cytoscape({container:container.current,elements:data.elements,style:graphStyle(palette()),layout:{name:'circle',fit:false},wheelSensitivity:0.25,maxZoom:1.6});
      cy.current.on('tap','node',event => onOpen(event.target.data('entity'),event.target.id()));
      cy.current.on('tap','edge',event => {
        const edge = event.target;
        onEdge({...edge.data(),sourceName:edge.source().data('label'),targetName:edge.target().data('label')});
      });
      physics.current = graphPhysics(cy.current,gravityRef.current,matchMedia('(prefers-reduced-motion: reduce)').matches);
      cy.current.fit(undefined,35);
    }).catch(e => {if(!cancelled) onError(e.message);});
    return () => {cancelled=true;physics.current?.destroy();physics.current=null;cy.current?.destroy();cy.current=null;};
  },[domain,level,focus,catalog]);
  useEffect(() => {cy.current?.style(graphStyle(palette()));},[theme]);
  const records = level === 'domains' ? catalog.domains : catalog.concepts;
  const nodes = new Map(result?.elements.filter(x=>!x.data.source).map(x=>[x.data.id,x.data.label]) ?? []);
  const edges = result?.elements.filter(x=>x.data.source) ?? [];
  return <section className="graph-panel">
    <div className="filters graph-controls">
      <label>View <HTMLSelect id="graphLevel" value={level} onChange={e=>{setLevel(e.target.value);setFocus('');}} options={[{value:'concepts',label:'Concepts'},{value:'domains',label:'Domains'},{value:'hierarchy',label:'Hierarchy'}]} /></label>
      <label>Focus <HTMLSelect id="graphFocus" value={focus} onChange={e=>setFocus(e.target.value)} options={[{value:'',label:'All nodes'},...records.map(r=>({value:r.id,label:r.name}))]} /></label>
      <Button id="fitGraph" small onClick={()=>cy.current?.fit(undefined,35)}>Fit</Button>
      <div className="gravity-control"><label id="gravityLabel">Gravity <output>{gravity.toFixed(1)}</output></label><Slider min={0} max={10} stepSize={0.5} labelStepSize={5} value={gravity} onChange={setGravity} onRelease={value=>physics.current?.setGravity(value)} handleHtmlProps={{'aria-label':'Node gravity'}} /></div>
    </div>
    <div id="graph" ref={container} role="img" aria-label="Knowledge graph. Drag nodes; scroll to zoom. Accessible connections below." />
    <div className="graph-meta"><span id="graphCount">{result ? `${result.shown_nodes} ${result.shown_nodes===1 ? 'node':'nodes'} · ${edges.length} ${edges.length===1 ? 'connection':'connections'}` : 'Loading graph…'}{result?.truncated && ` · ${result.total_nodes} total; narrow the focus`}</span><span>Drag nodes · scroll to zoom</span></div>
    <details><summary>Connections</summary><div id="connectionList">{edges.map(({data})=><Button key={data.id} minimal className="related" onClick={()=>onEdge({...data,sourceName:nodes.get(data.source),targetName:nodes.get(data.target)})}>{nodes.get(data.source)} ↔ {nodes.get(data.target)}</Button>)}{result && !edges.length && <p className="muted">No connections in this view.</p>}</div></details>
  </section>;
}
function Editor({entity,data,catalog,onChange,onClose,onSave,onOpenConcept,onOpenDomain,isCurrent,onOpenExisting}) {
  const [busy,setBusy] = useState(false), [status,setStatus] = useState(''), [error,setError] = useState(null), [original,setOriginal] = useState(null), [lookup,setLookup] = useState('');
  const entry = entity === 'entries', concept = entity === 'concepts', hasMath = entry || concept;
  const bodyKey = entry ? 'body' : 'definition';
  const errors = hasMath ? validateMath(data[bodyKey],data.latex) : [];
  if (hasMath && !data.latex) errors.unshift('A technical LaTeX expression is required.');
  const change = (key,value) => {setError(null);onChange({...data,[key]:value});};
  const toggle = (key,id,checked) => change(key,checked ? [...data[key],id] : data[key].filter(x=>x!==id));
  const parents = entry ? data.concept_ids : concept ? data.domain_ids : [];
  const invalid = !!errors.length || (hasMath && !parents.length);
  async function generate() {
    const initial = data;
    setBusy(true);setStatus('Drafting…');setError(null);setOriginal(prev=>prev ?? data);
    try {
      const request = entry ? {text:data.body,kind:data.kind,concept_ids:data.concept_ids} : {name:data.name,aliases:data.aliasesText.split(',').map(x=>x.trim()).filter(Boolean),domain_ids:data.domain_ids,context:data.definition+(data.latex ? '\nDefining LaTeX: '+data.latex : '')};
      const draft = await api(entry ? 'draft' : 'draft/concept','POST',request);
      if (!isCurrent(initial)) {setStatus('Draft discarded; your edits are preserved.');return;}
      onChange(entry ? {...data,title:draft.entry.title,body:draft.entry.body,latex:draft.entry.latex} : {...data,definition:draft.concept.definition,latex:draft.concept.latex});
      setStatus('Review the mathematics before saving.');
    } catch(e) {setStatus(e.message);}
    finally {setBusy(false);}
  }
  async function save(e) {
    e.preventDefault();setBusy(true);setError(null);
    try {await onSave(data);} catch(e) {setError(e);} finally {setBusy(false);}
  }
  const label = entry ? 'entry' : entity.slice(0,-1);
  const heading = `${data.id ? 'Edit' : 'New'} ${label}`;
  return <Dialog isOpen title={heading} onClose={onClose} className="record-dialog" canOutsideClickClose={false}>
    <form onSubmit={save}>
      {entry ? <>
        <FormGroup label="Related concepts" labelFor="entryConceptLookup"><InputGroup id="entryConceptLookup" placeholder="Find concepts…" value={lookup} onChange={e=>setLookup(e.target.value)} /></FormGroup>
        <div className="choices">{catalog.concepts.filter(c=>data.concept_ids.includes(c.id) || [c.name,...c.aliases].some(n=>n.toLowerCase().includes(lookup.toLowerCase()))).map(c=><Checkbox key={c.id} label={c.name} checked={data.concept_ids.includes(c.id)} onChange={e=>toggle('concept_ids',c.id,e.target.checked)} />)}</div>
        <Button minimal small onClick={onOpenConcept}>＋ Create concept</Button>
      </> : <>
        <FormGroup label="Name" labelFor={`${entity}Name`}><InputGroup id={`${entity}Name`} required maxLength={160} value={data.name} onChange={e=>change('name',e.target.value)} /></FormGroup>
        <FormGroup label="Aliases" labelFor={`${entity}Aliases`}><InputGroup id={`${entity}Aliases`} placeholder="Comma-separated" value={data.aliasesText} onChange={e=>change('aliasesText',e.target.value)} /></FormGroup>
      </>}
      {hasMath && <>
        <FormGroup label={entry ? 'English / Markdown' : 'English definition / Markdown'} labelFor={`${entity}Body`}><TextArea id={`${entity}Body`} fill required rows={3} value={data[bodyKey]} onChange={e=>change(bodyKey,e.target.value)} /></FormGroup>
        {entry && <div className="form-row"><FormGroup label="Title" labelFor="entryTitle"><InputGroup id="entryTitle" required maxLength={160} placeholder="Short descriptive label" value={data.title} onChange={e=>change('title',e.target.value)} /></FormGroup><FormGroup label="Kind" labelFor="entryKind"><HTMLSelect id="entryKind" value={data.kind} options={kinds} onChange={e=>change('kind',e.target.value)} /></FormGroup></div>}
        <FormGroup label={entry ? 'Technical LaTeX' : 'Technical LaTeX definition'} labelFor={`${entity}Latex`} helperText="Bare LaTeX here; use $…$ for inline math in Markdown."><TextArea id={`${entity}Latex`} fill required rows={3} spellCheck={false} value={data.latex} onChange={e=>change('latex',e.target.value)} /></FormGroup>
        {concept && <><FormGroup label="Domains"><div className="choices">{catalog.domains.map(d=><Checkbox key={d.id} label={d.name} checked={data.domain_ids.includes(d.id)} onChange={e=>toggle('domain_ids',d.id,e.target.checked)} />)}</div></FormGroup><Button minimal small onClick={onOpenDomain}>＋ Create domain</Button></>}
        <div className="draft-row"><Button id={`${entity}Generate`} small loading={busy} disabled={busy} onClick={generate}>{entry ? 'Draft entry' : 'Draft definition'}</Button><span className="muted" role="status">{status}</span></div>
        {original && (original[bodyKey] || original.latex) && <details><summary>Original text</summary><pre>{original[bodyKey]}{original.latex && '\n\n'+original.latex}</pre><Button small onClick={()=>onChange({...data,[bodyKey]:original[bodyKey],latex:original.latex})}>Restore original</Button></details>}
        <div className="preview">{data.latex && !errors.length && <Rich text={data.latex} math />}<Rich text={data[bodyKey]} /></div>
      </>}
      {invalid && <p className="error">{errors.join('\n')}{hasMath && !parents.length && '\nSelect at least one parent.'}</p>}
      {error && <p className="error" role="alert">{error.message}{error.existingId && entry && <Button small onClick={()=>{onClose();onOpenExisting(error.existingId);}}>Open existing entry</Button>}</p>}
      <div className="dialog-actions"><Button onClick={onClose}>Cancel</Button><Button intent="primary" type="submit" loading={busy} disabled={invalid || busy}>Save {label}</Button></div>
    </form>
  </Dialog>;
}
function Reader({current,catalog,onOpen,onEdit,onDelete,onClose}) {
  const name = (entity,id) => catalog[entity]?.find(r=>r.id===id)?.name ?? id;
  if (!current) return <aside className="detail empty-reader" id="detail"><p>Select a record.</p></aside>;
  if (current.loading) return <aside className="detail" id="detail"><Spinner size={20} /></aside>;
  const {entity,record,related,edge} = current;
  const link = (entity,id,label) => <Button key={id} minimal className="related" onClick={()=>onOpen(entity,id)}>{label ?? name(entity,id)}</Button>;
  return <aside className="detail" id="detail" aria-label="Selected record">
    <div className="reader-top"><span className="type">{edge ? 'Connection' : entity === 'entries' ? record.kind : entity.slice(0,-1)}</span><Button small minimal aria-label="Close reader" icon="cross" onClick={onClose} /></div>
    <h2>{edge ? `${edge.sourceName} ↔ ${edge.targetName}` : record.title ?? record.name}</h2>
    {!edge && entity !== 'domains' && <p className="opened">Last opened {openedLabel(record.last_opened_at)}</p>}
    {edge ? <><h3>Supporting records</h3>{edge.concept_ids.map(id=>link('concepts',id))}{related.items.map(({record:r})=>link('entries',r.id,r.title))}{!edge.concept_ids.length && !related.items.length && <p className="muted">Parent relationship.</p>}</> : <>
      {record.latex && <WrappedFormula text={record.latex} className="reader-math" />}
      <Rich text={record.body ?? record.definition ?? ''} className="body" />
      {record.aliases?.length>0 && <p className="muted">Aliases: {record.aliases.join(', ')}</p>}
      {entity==='entries' && <><h3>Concepts</h3>{record.concept_ids.map(id=>link('concepts',id))}</>}
      {entity==='concepts' && <><h3>Domains</h3>{record.domain_ids.map(id=>link('domains',id))}</>}
      {entity==='domains' && <><h3>Concepts</h3>{catalog.concepts.filter(c=>c.domain_ids.includes(record.id)).map(c=>link('concepts',c.id))}</>}
      {related && <><h3>Related entries · {related.total}</h3>{related.items.map(({record:r})=>link('entries',r.id,r.title))}</>}
      <div className="detail-actions"><Button small icon="edit" onClick={onEdit}>Edit</Button><Button small minimal intent="danger" icon="trash" onClick={onDelete}>Delete</Button></div>
    </>}
  </aside>;
}
function App() {
  const [theme,setTheme] = useState(()=>{try {return localStorage.getItem('poleq-theme') ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark':'light');} catch {return 'light';}});
  const [catalog,setCatalog] = useState({domains:[],concepts:[]}), [count,setCount] = useState(0), [epoch,setEpoch] = useState(0), [model,setModel] = useState(null);
  const [filter,setFilter] = useState({q:'',entity:'',kind:'',domain:'',concepts:[],mode:'any',stale:''}), [view,setView] = useState('library'), [lookup,setLookup] = useState('');
  const [items,setItems] = useState([]), [total,setTotal] = useState(0), [offset,setOffset] = useState(0), [loading,setLoading] = useState(true);
  const [level,setLevel] = useState('concepts'), [focus,setFocus] = useState(''), [gravity,setGravity] = useState(4);
  const [current,setCurrent] = useState(null), [notice,setNotice] = useState(''), [editors,setEditors] = useState({entries:null,concepts:null,domains:null});
  const editorRef = useRef(editors), selection = useRef(0), importFile = useRef(null), main = useRef(null);
  editorRef.current = editors;
  const name = (entity,id) => catalog[entity]?.find(r=>r.id===id)?.name ?? id;
  useEffect(()=>{document.documentElement.dataset.theme=theme;document.body.classList.toggle('bp6-dark',theme==='dark');try {localStorage.setItem('poleq-theme',theme);} catch {}},[theme]);
  useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),6500);return()=>clearTimeout(timer);},[notice]);
  async function refresh() {
    const [data,health] = await Promise.all([api('catalog'),api('health')]);
    setCatalog(data);setCount(Object.values(health.counts).reduce((a,b)=>a+b,0));setEpoch(x=>x+1);
  }
  useEffect(()=>{refresh().catch(e=>setNotice(e.message));api('model').then(setModel).catch(()=>{});},[]);
  useEffect(()=>{
    let cancelled=false;
    const timer=setTimeout(()=>{
      setLoading(true);
      const p=new URLSearchParams({q:filter.q,mode:filter.mode,limit:'40',offset:String(offset)});
      if(filter.entity)p.set('entity',filter.entity);if(filter.kind)p.set('kind',filter.kind);if(filter.domain)p.set('domain_id',filter.domain);
      const stale=staleWindows[filter.stale];
      if(stale){p.set('stale_days',stale[0]);if(stale[1])p.set('stale_max_days',stale[1]);}
      filter.concepts.forEach(id=>p.append('concept_id',id));
      api('search?'+p).then(data=>{if(!cancelled){setItems(prev=>offset ? [...prev,...data.items] : data.items);setTotal(data.total);setLoading(false);}}).catch(e=>{if(!cancelled){setLoading(false);setNotice(e.message);}});
    },filter.q ? 180:0);
    return()=>{cancelled=true;clearTimeout(timer);};
  },[filter,offset,epoch]);
  const changeFilter = changes => {setOffset(0);setFilter(prev=>({...prev,...changes}));main.current?.scrollTo({top:0});};
  const setEntity = entity => changeFilter({entity,...(entity==='domains' ? {stale:''} : {})});
  const clearFilters = () => {changeFilter({q:'',entity:'',kind:'',domain:'',concepts:[],mode:'any',stale:''});setFocus('');};
  async function openRecord(entity,id) {
    const token=++selection.current;setCurrent({loading:true});
    try {
      const record=await api(`${entity}/${id}`);
      if(entity!=='domains')api(`${entity}/${id}/opened`,'POST').catch(()=>{});
      let related=null;
      if(entity!=='entries') {
        const p=new URLSearchParams({entity:'entries',limit:'500'});p.set(entity==='domains' ? 'domain_id':'concept_id',id);related=await api('search?'+p);
      }
      if(token===selection.current)setCurrent({entity,record,related});
    } catch(e) {if(token===selection.current){setCurrent(null);setNotice(e.message);}}
  }
  async function openEdge(edge) {
    const token=++selection.current;setCurrent({loading:true});
    try {
      const records=await Promise.all(edge.entry_ids.map(id=>api('entries/'+id)));
      if(token===selection.current)setCurrent({edge,related:{items:records.map(record=>({record}))}});
    } catch(e) {if(token===selection.current){setCurrent(null);setNotice(e.message);}}
  }
  function openEditor(entity,record=null) {
    const data=record ? {...record,aliasesText:record.aliases?.join(', ') ?? ''} : entity==='entries' ? {title:'',kind:'property',body:'',latex:'',concept_ids:[...filter.concepts]} : entity==='concepts' ? {name:'',aliasesText:'',definition:'',latex:'',domain_ids:filter.domain ? [filter.domain]:[]} : {name:'',aliasesText:''};
    setEditors(prev=>({...prev,[entity]:data}));
  }
  async function saveEditor(entity,data) {
    const payload=entity==='entries' ? {title:data.title,kind:data.kind,body:data.body,latex:data.latex,concept_ids:data.concept_ids} : {name:data.name,aliases:data.aliasesText.split(',').map(x=>x.trim()).filter(Boolean),...(entity==='concepts' ? {definition:data.definition,latex:data.latex,domain_ids:data.domain_ids}:{})};
    const record=await api(data.id ? `${entity}/${data.id}`:entity,data.id ? 'PUT':'POST',payload);
    setEditors(prev=>({...prev,[entity]:null,...(entity==='concepts' && prev.entries ? {entries:{...prev.entries,concept_ids:[...new Set([...prev.entries.concept_ids,record.id])]}}:{}),...(entity==='domains' && prev.concepts ? {concepts:{...prev.concepts,domain_ids:[...new Set([...prev.concepts.domain_ids,record.id])]}}:{})}));
    setOffset(0);await refresh();await openRecord(entity,record.id);setNotice('Saved.');
  }
  async function removeRecord() {
    if(!current?.record || !confirm('Delete this record? A backup will be saved first.'))return;
    try {await api(`${current.entity}/${current.record.id}`,'DELETE');setCurrent(null);clearFilters();await refresh();setNotice('Deleted.');} catch(e) {setNotice(e.message);}
  }
  async function restore(e) {
    const file=e.target.files[0];if(!file)return;
    try {
      const archive=JSON.parse(await file.text());
      if(!confirm('Replace this library with the selected file? A backup will be saved first.'))return;
      await api('import?replace=true','POST',archive);setCurrent(null);clearFilters();await refresh();setNotice('Library restored.');
    } catch(e) {setNotice(e.message);} finally {importFile.current.value='';}
  }
  const matches=(record)=>[record.name,...record.aliases].some(n=>n.toLowerCase().includes(lookup.toLowerCase()));
  return <div className={`workspace ${current ? 'reader-open':''}`}>
    <aside className="sidebar" aria-label="Library navigation">
      <a className="brand" href="/">PolEQ</a>
      <div className="sidebar-scroll">
        <Button id="allKnowledge" minimal className="nav" active={!filter.domain && !filter.concepts.length} onClick={clearFilters}>All knowledge <span className="count">{count}</span></Button>
        <div className="section-heading"><h2>Domains</h2><Button minimal small icon="plus" aria-label="Add domain" onClick={()=>openEditor('domains')} /></div>
        <div id="domains">{catalog.domains.map(d=><Button key={d.id} minimal className="nav" active={filter.domain===d.id} onClick={()=>{changeFilter({domain:filter.domain===d.id ? '':d.id,concepts:[]});setFocus('');}}>{d.name}</Button>)}</div>
        <div className="section-heading"><h2>Concepts</h2><Button minimal small icon="plus" aria-label="Add concept" onClick={()=>openEditor('concepts')} /></div>
        <InputGroup id="conceptLookup" small type="search" aria-label="Find a concept" placeholder="Find concept…" value={lookup} onChange={e=>setLookup(e.target.value)} />
        <div id="concepts">{catalog.concepts.filter(c=>(!filter.domain || c.domain_ids.includes(filter.domain)) && matches(c)).map(c=><Button key={c.id} minimal className="nav" active={filter.concepts.includes(c.id)} aria-pressed={filter.concepts.includes(c.id)} onClick={()=>{if(view==='graph'){changeFilter({concepts:[c.id]});setLevel('concepts');setFocus(c.id);}else changeFilter({concepts:filter.concepts.includes(c.id) ? filter.concepts.filter(id=>id!==c.id):[...filter.concepts,c.id]});}}>{c.name}</Button>)}</div>
      </div>
      <div className="sidebar-footer">
        <Button id="newEntry" fill intent="primary" icon="plus" onClick={()=>openEditor('entries')}>New entry</Button>
        <div className="file-actions"><Button id="export" small onClick={()=>{window.location.href='/api/export';}}>Export</Button><Button id="import" small onClick={()=>importFile.current.click()}>Restore</Button><Button id="backup" small onClick={()=>api('backup','POST').then(r=>setNotice(r.path ? 'Backup saved.':'Library is empty.')).catch(e=>setNotice(e.message))}>Backup</Button></div>
        <div className="theme-row"><span id="modelStatus" className="model-status" title={model?.message ?? model?.model}>{model?.available ? model.model : 'Model offline'}</span><Button id="themeToggle" small minimal icon={theme==='dark' ? 'flash':'moon'} aria-label={`Switch to ${theme==='dark' ? 'light':'dark'} mode`} onClick={()=>setTheme(theme==='dark' ? 'light':'dark')}>{theme==='dark' ? 'Light':'Dark'}</Button></div>
      </div>
    </aside>
    <main ref={main}>
      <div className="heading"><h1>{filter.domain ? name('domains',filter.domain):'All knowledge'}</h1><div className="tabs" role="group" aria-label="View"><Button id="libraryTab" small minimal active={view==='library'} aria-pressed={view==='library'} onClick={()=>setView('library')}>Library</Button><Button id="graphTab" small minimal active={view==='graph'} aria-pressed={view==='graph'} onClick={()=>setView('graph')}>Graph</Button></div></div>
      {view==='library' ? <section id="libraryView">
        <InputGroup id="search" type="search" leftIcon="search" aria-label="Search knowledge" placeholder="Search keywords, concepts, formulas…" value={filter.q} onChange={e=>changeFilter({q:e.target.value})} />
        <div className="filters"><label>Show <HTMLSelect id="entity" value={filter.entity} onChange={e=>setEntity(e.target.value)} options={[{value:'',label:'Everything'},{value:'entries',label:'Entries'},{value:'concepts',label:'Concepts'},{value:'domains',label:'Domains'}]} /></label><label>Kind <HTMLSelect id="kind" value={filter.kind} onChange={e=>changeFilter({kind:e.target.value})} options={[{value:'',label:'All'},...kinds]} /></label><label>Match <HTMLSelect id="matchMode" value={filter.mode} onChange={e=>changeFilter({mode:e.target.value})} options={[{value:'any',label:'Any concept'},{value:'all',label:'All concepts'}]} /></label><label>Opened <HTMLSelect id="stale" value={filter.stale} onChange={e=>changeFilter({stale:e.target.value})} options={[{value:'',label:'Any time'},{value:'15',label:'15–30 days'},{value:'30',label:'30–45 days'},{value:'45',label:'45+ days'}]} /></label><Button small minimal id="clearFilters" onClick={clearFilters}>Clear</Button></div>
        {filter.concepts.length>0 && <div className="selected-filters">{filter.concepts.map(id=><Button key={id} small minimal rightIcon="cross" onClick={()=>changeFilter({concepts:filter.concepts.filter(c=>c!==id)})}>{name('concepts',id)}</Button>)}</div>}
        <div className="list-meta"><span id="resultCount" aria-live="polite">{loading ? 'Searching…':`${total} ${total===1 ? 'result':'results'}`}</span><details className="kind-key"><summary>Types</summary><div>{['domain','concept',...kinds].map(kind=><span key={kind} className={'kind-'+kind}>{kind}</span>)}</div></details></div>
        <div id="results">{items.map(({entity,record,last_opened_at})=><RecordCard key={record.id} entity={entity} record={record} opened={last_opened_at} selected={current?.record?.id===record.id} onOpen={openRecord} />)}</div>
        {!loading && !items.length && <div className="empty-state"><p>No results.</p>{!catalog.domains.length && <Button onClick={()=>openEditor('domains')}>Add domain</Button>}</div>}
        {items.length<total && <Button id="more" small loading={loading} onClick={()=>setOffset(offset+40)}>Load more</Button>}
      </section> : <Graph catalog={catalog} domain={filter.domain} level={level} focus={focus} setLevel={setLevel} setFocus={setFocus} gravity={gravity} setGravity={setGravity} theme={theme} onOpen={openRecord} onEdge={openEdge} onError={setNotice} />}
    </main>
    <Reader current={current} catalog={catalog} onOpen={openRecord} onEdit={()=>openEditor(current.entity,current.record)} onDelete={removeRecord} onClose={()=>{selection.current++;setCurrent(null);}} />
    {Object.entries(editors).filter(([,data])=>data).map(([entity,data])=><Editor key={entity} entity={entity} data={data} catalog={catalog} onChange={next=>setEditors(prev=>({...prev,[entity]:next}))} onClose={()=>setEditors(prev=>({...prev,[entity]:null}))} onSave={data=>saveEditor(entity,data)} onOpenConcept={()=>openEditor('concepts')} onOpenDomain={()=>openEditor('domains')} isCurrent={initial=>editorRef.current[entity]===initial} onOpenExisting={id=>openRecord('entries',id)} />)}
    <input type="file" ref={importFile} onChange={restore} accept=".json,application/json" hidden />
    {notice && <div id="notice" role="status">{notice}<Button small minimal icon="cross" aria-label="Dismiss message" onClick={()=>setNotice('')} /></div>}
  </div>;
}
createRoot(document.getElementById('root')).render(<App />);
