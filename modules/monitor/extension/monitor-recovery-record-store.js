// Recovery-owned collections. Other feature modules see only typed read/write
// methods, not the underlying Maps/Sets or their DOM.
(() => {
  "use strict";
  function mapFacade() {
    const map=new Map();
    const api={
      get:key=>map.get(key),
      has:key=>map.has(key),
      set(key,value){map.set(key,value);return api;},
      delete:key=>map.delete(key),
      clear:()=>map.clear(),
      values:()=>map.values(),
      entries:()=>map.entries(),
      keys:()=>map.keys(),
      get size(){return map.size;},
      [Symbol.iterator]:()=>map.entries()
    };
    return Object.freeze(api);
  }
  function setFacade() {
    const set=new Set();
    const api={
      has:key=>set.has(key),
      add(key){set.add(key);return api;},
      delete:key=>set.delete(key),
      clear:()=>set.clear(),
      values:()=>set.values(),
      get size(){return set.size;},
      [Symbol.iterator]:()=>set.values()
    };
    return Object.freeze(api);
  }
  function create() {
    return Object.freeze({
      ghosts:mapFacade(),trash:mapFacade(),trashedKeys:setFacade()
    });
  }
  globalThis.MonitorRecoveryRecordStore=Object.freeze({create});
})();
