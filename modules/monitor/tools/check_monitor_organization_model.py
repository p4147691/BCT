from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

def extract_top_level_function(text, name):
    m = re.search(r'(?:async\s+)?function\s+' + re.escape(name) + r'\s*\(', text)
    if not m:
        raise RuntimeError('FUNCTION_NOT_FOUND ' + name)
    start = m.start()
    nxt = re.search(r'\n(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\(', text[m.end():])
    end = m.end() + nxt.start() if nxt else len(text)
    return text[start:end].strip()

def main():
    parser = argparse.ArgumentParser(description='Verify DesktopWindow Monitor connection-first organization invariants')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root)
    source = root / 'extension' / 'monitor.js'
    text = source.read_text(encoding='utf-8', errors='replace')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    names = ['monitorStructureDefaultParents', 'monitorStructureEffectiveParents', 'monitorStructureAuthorityOverrides', 'monitorStructureWouldCycle', 'monitorStructureBuildSavePayload']
    parts = [extract_top_level_function(text, n) for n in names]

    js = '\n\n'.join(parts) + r'''
let monitorStructureLinkOverrides={};
let monitorStructureResourceEdges=[{supervisor_key:'M1',resource_id:'R1',relation:'USES'}];
let monitorStructureOrganizationGeneration=7;

const baseLayout={
  orchestrator:{conversation_key:'O'}, aux1:null, aux2:null,
  desktops:{
    D1:{index:0,manager:{conversation_key:'M1'},workers:[{conversation_key:'W1'},{conversation_key:'W2'}]},
    D2:{index:1,manager:{conversation_key:'M2'},workers:[{conversation_key:'W3'}]}
  }
};
const base=monitorStructureEffectiveParents(baseLayout);

const newNodeLayout=JSON.parse(JSON.stringify(baseLayout));
newNodeLayout.desktops.D1.workers.push({conversation_key:'W4'});
const newNode=monitorStructureEffectiveParents(newNodeLayout);

const movedLayout=JSON.parse(JSON.stringify(baseLayout));
movedLayout.desktops.D1.workers=movedLayout.desktops.D1.workers.filter(n=>n.conversation_key!=='W1');
movedLayout.desktops.D2.workers.push({conversation_key:'W1'});
const moved=monitorStructureEffectiveParents(movedLayout);

const managerSwap={orchestrator:{conversation_key:'O'},aux1:null,aux2:null,desktops:{
  D1:{index:0,manager:{conversation_key:'MN'},workers:[{conversation_key:'W1'},{conversation_key:'W2'},{conversation_key:'M1'}]}
}};
const swappedDefault=monitorStructureEffectiveParents(managerSwap);

const savedDefaultEdges=Object.entries(base).map(([child_key,parent_key])=>({child_key,parent_key,relation:'MANAGES'}));
const normalizedDefault=monitorStructureAuthorityOverrides({edges:savedDefaultEdges,detached_children:[]},baseLayout);
monitorStructureLinkOverrides=normalizedDefault;
const swappedAfterDefaultRoundTrip=monitorStructureEffectiveParents(managerSwap);

const explicitAuthority=monitorStructureAuthorityOverrides({
  edges:[...savedDefaultEdges,{child_key:'W1',parent_key:'SPECIAL',relation:'MANAGES'}],
  detached_children:['W2']
},baseLayout);
monitorStructureLinkOverrides=explicitAuthority;
const swappedAfterExplicitRoundTrip=monitorStructureEffectiveParents(managerSwap);

monitorStructureLinkOverrides={W1:'SPECIAL',W2:null};
const swappedOverride=monitorStructureEffectiveParents(managerSwap);

const cycleParents={A:'B',B:'C'};
const cycle=monitorStructureWouldCycle('C','A',cycleParents);
const safe=monitorStructureWouldCycle('D','A',cycleParents);

monitorStructureLinkOverrides={W2:null};
function monitorStructureAutoLayout(){return baseLayout;}
const payload=monitorStructureBuildSavePayload();

console.log(JSON.stringify({base,newNode,moved,swappedDefault,normalizedDefault,swappedAfterDefaultRoundTrip,explicitAuthority,swappedAfterExplicitRoundTrip,swappedOverride,cycle,safe,payload}));
'''

    proc = subprocess.run(['node','-e',js], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    if proc.returncode != 0:
        print(json.dumps({'ok':False,'source_sha256':source_hash,'error':'NODE_EXEC_FAILED','stderr':proc.stderr}, ensure_ascii=False, indent=2))
        return 1
    data = json.loads(proc.stdout.strip())
    errors = []
    def check(label, cond):
        if not cond:
            errors.append(label)

    check('base W1 -> M1', data['base'].get('W1') == 'M1')
    check('base W2 -> M1', data['base'].get('W2') == 'M1')
    check('base W3 -> M2', data['base'].get('W3') == 'M2')
    check('new W4 auto -> M1', data['newNode'].get('W4') == 'M1')
    check('desk-moved W1 -> M2', data['moved'].get('W1') == 'M2')
    check('manager-swap W1 -> MN', data['swappedDefault'].get('W1') == 'MN')
    check('former M1 becomes child of MN', data['swappedDefault'].get('M1') == 'MN')
    check('explicit reparent overrides default', data['swappedOverride'].get('W1') == 'SPECIAL')
    check('explicit null detaches default', 'W2' not in data['swappedOverride'])
    check('saved default edges normalize to no overrides', data['normalizedDefault'] == {})
    check('default roundtrip remains manager-relative', data['swappedAfterDefaultRoundTrip'].get('W1') == 'MN' and data['swappedAfterDefaultRoundTrip'].get('W2') == 'MN')
    check('authority explicit reparent remains override', data['explicitAuthority'].get('W1') == 'SPECIAL')
    check('authority detached child remains explicit null', 'W2' in data['explicitAuthority'] and data['explicitAuthority'].get('W2') is None)
    check('explicit authority survives manager swap', data['swappedAfterExplicitRoundTrip'].get('W1') == 'SPECIAL' and 'W2' not in data['swappedAfterExplicitRoundTrip'])
    check('cycle detected', data['cycle'] is True)
    check('safe parent accepted', data['safe'] is False)

    payload = data['payload']
    edges = {(e.get('child_key'),e.get('parent_key')) for e in payload.get('edges',[])}
    check('payload W1 MANAGES edge', ('W1','M1') in edges)
    check('payload W3 MANAGES edge', ('W3','M2') in edges)
    check('detached W2 has no edge', not any(c == 'W2' for c,p in edges))
    check('detached W2 serialized', 'W2' in payload.get('detached_children',[]))
    check('generation preserved', payload.get('expected_generation') == 7)
    check('actor preserved', payload.get('actor') == 'USER_MONITOR')
    check('resource edge preserved', payload.get('resource_edges') == [{'supervisor_key':'M1','resource_id':'R1','relation':'USES'}])

    renderer_ok = bool(re.search(r'function\s+monitorStructureDrawLinks\(layout\).*?Object\.entries\(monitorStructureEffectiveParents\(layout\)\)', text, re.S))
    check('UI renderer consumes effective parents', renderer_ok)
    edge_legend_ok = '선=실제 관리 연결' in text
    manager_role_label_ok = 'managerCaption.textContent="M";' in text
    redundant_desk_button_role = 'wrap.setAttribute("role","button")' in text
    check('connection UI explains management semantics when enabled', edge_legend_ok or '노드 드래그: 노드에 놓아 연결' in text)
    check('manager uses the compact M role label', manager_role_label_ok)
    check('Desk uses one final group role instead of redundant button/group rewrites', not redundant_desk_button_role)
    command_slots_ok = 'const commandSlots=[' in text and '["O","orchestrator",layout.orchestrator]' in text and '["C1","aux1",layout.aux1]' in text and '["C2","aux2",layout.aux2]' in text
    manager_first_auto_projection = ('const isExempt=(node)=>' in text and 'manual||roleManager||all.find(n=>!isExempt(n))||null' in text)
    permanent_manager_slot = 'monitorStructureRenderSocket(socket,group.manager||null);' in text
    density_scale_from_d7 = 'const compactLowerDesks=desktopCount>=7;' in text and 'compactAvailableWidth/compactNaturalWidth' in text
    empty_desk_projection_ok = 'function monitorStructureDeskNodeGrid(nodes,desktopId)' in text and 'grid.append(...bundles,monitorStructureDeskTransferSlot(desktopId));' in text
    resource_desk_ok = 'const resourceDesk=ids[ids.length-1]||"";' in text and 'if(!monitorStructureBundleDesk[kind]&&resourceDesk)' in text
    compact_node_number_ok = 'function monitorStructureNodeShortNumber(node)' in text and 'const numberText=compact?monitorStructureNodeShortNumber(node)' in text and 'if(!compact){' in text
    connection_drag_enabled = ('const MONITOR_STRUCTURE_CONNECTIONS_ENABLED=true;' in text and '<svg id="monitorStructureLinks"' in text and 'monitorStructurePointerTargetAt' in text and 'monitorStructureConnectNodesByPosition' in text and 'monitorStructureDetachBlankStep(nodeKey)' in text)
    physical_node_dedup = 'function monitorStructureNodeIdentityTokens(node)' in text and 'identityTokens.some(token=>seenPhysicalNodes.has(token))' in text and 'return [`act:${label}`]' in text and 'return [`tab:${tabId}:conversation:${conversationKey}`]' in text
    minimized_native_desktop_authority = (
        'function monitorMinimizedNodeSlotsByDesktop(state = monitorLastAiState)' in text
        and 'const desktopId = String(location?.desktopId || "").trim();' in text
        and 'if (!desktopId) continue;' in text
        and 'stable.desktopId || monitorDesktopState.desktopIds[Number(stable.desktop)-1]' not in text
    )
    minimized_exact_hwnd_identity = (
        'function monitorActNodeNumbersForHwnd(hwnd, state = monitorLastAiState)' in text
        and 'if(String(node?.identity_authority||"")!=="ACT_TAB_CHAT") continue;' in text
        and 'if(String(node?.hwnd||"").trim()!==key) continue;' in text
        and 'if(String(node?.location_authority||"")!=="ACT_NATIVE_OBSERVER") continue;' not in text
    )
    minimized_lightweight_projection = (
        'function renderLightweightDesktopCards()' in text
        and 'minimizedNodes.className = "monitor-desktop-minimized-nodes";' in text
        and 'label.append(badge, text); visual.append(minimizedNodes); button.append(visual, label);' in text
        and 'syncMonitorMinimizedNodeBadges();\n  return true;' in text
    )
    command_rail_ok = 'const workers=monitorStructureDeskNodeGrid(group.workers||[],desktopId);' in text and 'lowerDeskCount===1' in text and 'is-single-lower-desk' in text
    command_canvas_ok = 'roleRow.className="monitor-org-command-canvas";' in text and 'monitor-org-command-"+slotName' in text
    check('D1 always renders O/C1/C2 command slots', command_slots_ok)
    check('occupied lower Desk auto-fills manager slot first', manager_first_auto_projection)
    check('every lower Desk renders a permanent manager slot', permanent_manager_slot)
    check('D7+ computes one uniform lower-Desk density scale', density_scale_from_d7)
    check('every Desk exposes its next-node slot in the shared node grid', empty_desk_projection_ok)
    check('automatic layout collects resources in the last existing Desk', resource_desk_ok)
    check('organization cards show only short node numbers', compact_node_number_ok)
    check('node drag connection UI and blank-space detach are enabled', connection_drag_enabled)
    check('organization projection de-duplicates physical browser nodes', physical_node_dedup)
    check('minimized badges use Native desktop identity without ACT desktop-number fallback', minimized_native_desktop_authority)
    check('minimized badges accept exact ACT HWND identity when observer projection is absent', minimized_exact_hwnd_identity)
    check('lightweight desktop cards re-project minimized badges after replacement', minimized_lightweight_projection)
    check('D1/D2 share node-grid ordering and a single lower desk stays centered', command_rail_ok)
    check('D1 uses its own command-canvas DOM instead of the Desk grid', command_canvas_ok)
    authority_success_uses_act = (
        'try{await monitorStructureRefreshAuthority();monitorStructureAuthorityLoaded=true;authorityOk=true;}' in text
        and 'const baseline=monitorStructureReconcileSnapshot(storedBaseline);' in text
        and 'const working=monitorStructureReconcileSnapshot(storedWorking);' in text
        and 'if(working){' in text
        and 'if(baseline){' in text
    )
    stale_success_reload = (
        'MONITOR_STRUCTURE_TEMP_DRAFT_KEY' in text
        or 'ACT 구조 조회 실패 · 임시저장 배치 사용' in text
        or 'ACT 구조 조회 실패 · 로컬 저장 배치 사용' in text
    )
    check('ACT refresh applies only a compatible last-stable layout', authority_success_uses_act and not stale_success_reload)

    result = {'ok':not errors,'source_sha256':source_hash,'errors':errors,'facts':{'base':data['base'],'newNode':data['newNode'],'moved':data['moved'],'swappedDefault':data['swappedDefault'],'normalizedDefault':data['normalizedDefault'],'swappedAfterDefaultRoundTrip':data['swappedAfterDefaultRoundTrip'],'explicitAuthority':data['explicitAuthority'],'swappedAfterExplicitRoundTrip':data['swappedAfterExplicitRoundTrip'],'swappedOverride':data['swappedOverride'],'payload_edges':payload.get('edges',[]),'detached_children':payload.get('detached_children',[]),'renderer_uses_effective_parents':renderer_ok,'edge_legend_ok':edge_legend_ok,'manager_role_label_ok':manager_role_label_ok,'command_slots_ok':command_slots_ok,'manager_first_auto_projection':manager_first_auto_projection,'permanent_manager_slot':permanent_manager_slot,'density_scale_from_d7':density_scale_from_d7,'empty_desk_projection_ok':empty_desk_projection_ok,'resource_desk_ok':resource_desk_ok,'compact_node_number_ok':compact_node_number_ok,'connection_drag_enabled':connection_drag_enabled,'physical_node_dedup':physical_node_dedup,'minimized_native_desktop_authority':minimized_native_desktop_authority,'minimized_exact_hwnd_identity':minimized_exact_hwnd_identity,'minimized_lightweight_projection':minimized_lightweight_projection,'command_rail_ok':command_rail_ok,'command_canvas_ok':command_canvas_ok,'redundant_desk_button_role':redundant_desk_button_role,'authority_success_uses_act':authority_success_uses_act,'stale_success_reload':stale_success_reload}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1

if __name__ == '__main__':
    raise SystemExit(main())
