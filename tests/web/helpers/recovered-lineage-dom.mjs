import assert from 'node:assert/strict';
class Node {
  constructor(tag='div',attrs={}) {this.tagName=tag.toUpperCase();this.attrs=attrs;this.children=[];this.parentElement=null;this.listeners=new Map();this.dataset={};this.value='';this._text='';this.hidden='hidden' in attrs;this.disabled='disabled' in attrs;this.scrollTop=0;this.scrollHeight=400;this.clientHeight=400;for(const [k,v] of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=v;}
  appendChild(n){this.append(n);return n;}
  removeEventListener(k,f){this.listeners.set(k,(this.listeners.get(k)??[]).filter(x=>x!==f));}
  get className(){return this.attrs.class??'';} set className(v){this.attrs.class=v;}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=v;this.children=[];}
  get firstElementChild(){return this.children[0]??null;}
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(k,f){const list=this.listeners.get(k)??[];list.push(f);this.listeners.set(k,list);}
  fire(k,extras={}){const e={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...extras};for(const f of this.listeners.get(k)??[])f(e);return e;}
  requestSubmit(){this.fire('submit');}
  focus(){this.focused=true;}
  setPointerCapture(){}
  querySelectorAll(selector){const matches=[];const match=n=>{if(selector.startsWith('[')){const [,key,value]=selector.match(/^\[([^=\]]+)(?:=['"]?([^'"\]]+)['"]?)?\]$/)??[];return key in n.attrs&&(value===undefined||n.attrs[key]===value);}if(selector.startsWith('.'))return n.className.split(/\s+/).includes(selector.slice(1));const [tag,cls]=selector.split('.');return n.tagName.toLowerCase()===tag&&(!cls||n.className.split(/\s+/).includes(cls));};const visit=n=>{for(const child of n.children){if(match(child))matches.push(child);visit(child);}};visit(this);return matches;}
  querySelector(s){if(s.includes(' ')){const [head,...rest]=s.split(' ');return this.querySelector(head)?.querySelector(rest.join(' '))??null;}return this.querySelectorAll(s)[0]??null;}
}
function parseHtml(source){
  const root=new Node('document'), stack=[root];const voids=new Set(['meta','link','input','img','br','hr','source','wbr']);
  for(const token of source.matchAll(/<!--[\s\S]*?-->|<![^>]+>|<\/?[a-zA-Z][^>]*>|[^<]+/g)){
    const value=token[0];if(value.startsWith('<!'))continue;
    if(value.startsWith('</')){const tag=value.slice(2,-1).trim().toLowerCase();assert.equal(stack.at(-1).tagName.toLowerCase(),tag,`shipping HTML closes ${tag} in the proper tree`);stack.pop();continue;}
    if(value.startsWith('<')){const [,tag,raw]=value.match(/^<([\w-]+)([\s\S]*?)\/?\s*>$/);const attrs={};for(const m of raw.matchAll(/([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))attrs[m[1]]=m[2]??m[3]??m[4]??'';const n=new Node(tag,attrs);stack.at(-1).append(n);if(!voids.has(tag)&&!value.endsWith('/>'))stack.push(n);}
    else stack.at(-1)._text+=value;
  }
  assert.equal(stack.length,1,'all shipping HTML elements close');
  for(const select of root.querySelectorAll('select')) {const options=select.querySelectorAll('option');select.value=(options.find(option=>'selected' in option.attrs)??options[0])?.attrs.value??'';}
  return root;
}

export {Node,parseHtml};
