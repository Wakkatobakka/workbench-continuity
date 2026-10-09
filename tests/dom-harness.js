// Minimal DOM for event-contract checks only, no rendered-browser claims.
'use strict';
const fs=require('node:fs');
const decode=s=>String(s||'').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
function DOM(htmlFile) {
  const ids=new Map(),dynamic=[];let sequence=0;
  class Element {
    constructor(tag='div',attrs={},owner=null){this.tagName=tag.toUpperCase();this.id=attrs.id||'';this.owner=owner;this.value=decode(attrs.value||'');this.textContent='';this.dataset={};this.style={};this.disabled=Object.hasOwn(attrs,'disabled');if(Object.hasOwn(attrs,'webkitdirectory'))this.webkitdirectory=true;this.files=[];this.events={};this.children=[];this.className=attrs.class||'';this.attrs=attrs;this.selectionStart=0;this._html='';for(const[k,v]of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=decode(v);const self=this;this.classList={add(n){const a=new Set(self.className.split(/\s+/));a.add(n);self.className=[...a].join(' ')},remove(n){self.className=self.className.split(/\s+/).filter(x=>x!==n).join(' ')},contains(n){return self.className.split(/\s+/).includes(n)},toggle(n,on){const yes=on===undefined?!this.contains(n):on;yes?this.add(n):this.remove(n);return yes}};}
    set innerHTML(html){this._html=html;for(const[id,el]of ids)if(el.owner===this||descends(el,this))ids.delete(id);for(let i=dynamic.length-1;i>=0;i--)if(dynamic[i].owner===this||descends(dynamic[i],this))dynamic.splice(i,1);parse(html,this);}
    get innerHTML(){return this._html}
    addEventListener(name,fn){(this.events[name]||=([])).push(fn)}
    async dispatch(name){const ev={target:this,preventDefault(){},returnValue:undefined};for(const fn of this.events[name]||[])await fn(ev);if(this['on'+name])return this['on'+name](ev)}
    click(){this.clickCount=(this.clickCount||0)+1;return this.onclick?this.onclick({target:this,preventDefault(){}}):undefined}
    focus(){this.focused=true}setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b}setAttribute(k,v){this.attrs[k]=String(v)}appendChild(el){this.children.push(el);return el}append(...els){this.children.push(...els)}remove(){}showModal(){}
  }
  function descends(el,parent){let p=el.owner;while(p){if(p===parent)return true;p=p.owner}return false}
  function parse(html,owner){
    const matches=[...html.matchAll(/<([a-z][\w-]*)\b([^>]*?)>/gi)];
    for(const m of matches){const attrs={};for(const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[a[1]]=a[2]??'';if(!attrs.id&&!Object.keys(attrs).some(k=>k.startsWith('data-')))continue;const e=new Element(m[1],attrs,owner);dynamic.push(e);if(e.id)ids.set(e.id,e);e.uniqueId=++sequence;
      if(m[1].toLowerCase()==='textarea'){const tail=html.slice(m.index+m[0].length),end=tail.indexOf('</textarea>');e.value=decode(end<0?'':tail.slice(0,end));}
      if(m[1].toLowerCase()==='select'){const tail=html.slice(m.index+m[0].length),end=tail.indexOf('</select>'),options=[...(end<0?'':tail.slice(0,end)).matchAll(/<option\b([^>]*)>/g)];let first='',selected;for(const op of options){const val=/value="([^"]*)"/.exec(op[1])?.[1]||'';if(!first)first=val;if(/\bselected\b/.test(op[1]))selected=val;}e.value=decode(selected===undefined?first:selected);}
    }
  }
  const body=new Element('body');const html=fs.readFileSync(htmlFile,'utf8');parse(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''),body);
  return {ids,body,getElementById:id=>ids.get(id)||null,querySelectorAll:selector=>{const attr=/^\[([\w-]+)\]$/.exec(selector)?.[1];return attr?dynamic.filter(e=>Object.hasOwn(e.attrs,attr)):[]},querySelector:()=>null,createElement:tag=>new Element(tag),title:'',Element};
}

module.exports={DOM};
