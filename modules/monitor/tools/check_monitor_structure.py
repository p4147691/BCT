from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description='Validate DesktopWindow Monitor structural invariants')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root)
    ext = root / 'extension'
    native = root / 'native'
    errors = []
    warnings = []
    facts = {}

    required = [
        root/'MONITOR_DEPENDENCY_AUDIT.md', root/'MONITOR_REBUILD_READINESS.md',
        ext/'AGENTS.md', ext/'MONITOR_STRUCTURE.md', ext/'MONITOR_JS_MAP.md',
        ext/'MONITOR_MODULE_BOUNDARIES.md', ext/'MONITOR_ORGANIZATION_MODEL.md', ext/'MONITOR_JS_INDEX.md',
        ext/'manifest.json', ext/'desktop.html', ext/'monitor.js', ext/'monitor.css',
        ext/'monitor-ui-layout.js', ext/'monitor-ui-layout.css',
        ext/'monitor-provider-launch-queue.js', ext/'monitor-act-transport.js',
        ext/'monitor-bct-node-interaction.js', ext/'monitor-bct-thumbnail-projection.js',
        ext/'monitor-thumbnail-contract.js', ext/'monitor-desktop-visual-source.js',
        ext/'monitor-thumbnail-background-layer.js', ext/'monitor-thumbnail-window-layer.js',
        ext/'monitor-desktop-thumbnail-v2.js',
        ext/'browser'/'tab-focus-adapter.js',
        root/'tools'/'Request-MonitorDeploymentCheck.ps1',
        root/'tools'/'Publish-MonitorDeployment.ps1',
        root/'tools'/'build_monitor_js_index.py',
        root/'tools'/'check_monitor_organization_model.py',
        root/'tools'/'check_monitor_live_organization.py',
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing: errors.append({'kind':'missing_required','paths':missing})

    org_doc_name = 'MONITOR_ORGANIZATION_MODEL.md'
    for route_doc in [ext/'AGENTS.md', ext/'MONITOR_STRUCTURE.md', ext/'MONITOR_MODULE_BOUNDARIES.md']:
        if route_doc.exists() and org_doc_name not in route_doc.read_text(encoding='utf-8', errors='replace'):
            errors.append({'kind':'organization_model_not_routed','path':str(route_doc),'required':org_doc_name})

    # Generated runtime is subordinate to the named, separately editable source parts.
    # Fail closed if a later agent patches the generated monolith directly.
    parts_manifest = root/'source-parts'/'manifest.json'
    if parts_manifest.exists():
        builder = root/'tools'/'build_monitor_bundle.py'
        if not builder.exists():
            errors.append({'kind':'monitor_source_parts_builder_missing'})
        else:
            build_check = subprocess.run(
                [sys.executable, str(builder), '--check'],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=20)
            facts['monitor_source_bundle_check'] = build_check.returncode
            if build_check.returncode != 0:
                errors.append({'kind':'monitor_source_bundle_out_of_sync',
                               'detail':(build_check.stdout+build_check.stderr)[-550:]})
        try:
            parts = json.loads(parts_manifest.read_text(encoding='utf-8'))['parts']
            if not isinstance(parts,list) or len(set(parts)) != len(parts):
                errors.append({'kind':'monitor_source_parts_manifest_invalid'})
            elif node := shutil.which('node'):
                for part in parts:
                    candidate = root/'source-parts'/part
                    result = subprocess.run(
                        [node, '--check', str(candidate)], capture_output=True, text=True,
                        encoding='utf-8', errors='replace', timeout=20)
                    if result.returncode != 0:
                        errors.append({'kind':'monitor_source_part_syntax', 'name':part})
            facts['monitor_source_parts_count'] = len(parts)
        except Exception as exc:
            errors.append({'kind':'monitor_source_parts_invalid','detail':str(exc)[:150]})

    dependency_audit = root/'tools'/'analyze_monitor_dependencies.py'
    if not dependency_audit.is_file():
        errors.append({'kind':'monitor_dependency_audit_tool_missing'})
    else:
        audit_check = subprocess.run(
            [sys.executable, str(dependency_audit), '--check'],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30)
        facts['monitor_dependency_audit_check'] = audit_check.returncode
        if audit_check.returncode != 0:
            errors.append({'kind':'monitor_dependency_audit_out_of_sync',
                           'detail':(audit_check.stdout+audit_check.stderr)[-350:]})

    domain_manifest = root/'domains'/'manifest.json'
    if (root/'source-parts'/'manifest.json').exists() and not domain_manifest.exists():
        errors.append({'kind':'monitor_domain_manifest_missing'})
    if domain_manifest.exists():
        try:
            domain_specs=json.loads(domain_manifest.read_text(encoding='utf-8'))['domains']
            if len(domain_specs) < 8 or len({x['domain'] for x in domain_specs}) != len(domain_specs):
                errors.append({'kind':'monitor_domain_manifest_invalid'})
            facts['monitor_function_domain_count']=len(domain_specs)
            for spec in domain_specs:
                p=root/'domains'/spec['file']
                if not p.is_file():
                    errors.append({'kind':'monitor_domain_file_missing','name':spec['file']})
                elif shutil.which('node'):
                    c=subprocess.run([shutil.which('node'),'--check',str(p)],
                        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
                    if c.returncode!=0:
                        errors.append({'kind':'monitor_domain_syntax_failed','name':spec['file']})
        except Exception as exc:
            errors.append({'kind':'monitor_domain_manifest_error','detail':str(exc)[:150]})

    # Stateless domain runtime must load before compatibility wrappers.
    pure_manifest = root/'domains'/'pure-api-manifest.json'
    if pure_manifest.is_file():
        try:
            spec=json.loads(pure_manifest.read_text(encoding='utf-8'))
            count=sum(len(names) for names in spec['namespaces'].values())
            api_js=ext/'monitor-domain-apis.js'
            scripts=(ext/'desktop.html').read_text(encoding='utf-8')
            prereq=(api_js.is_file()
              and '<script src="monitor-domain-apis.js"></script>' in scripts
              and scripts.index('<script src="monitor-domain-apis.js"></script>')<scripts.index('<script src="monitor.js"></script>')
              and spec['count']==count)
            facts['pure_domain_api_count']=count
            if not prereq:
                errors.append({'kind':'monitor_pure_domain_api_load_order_or_manifest_broken'})
            checker=root/'tools'/'check_monitor_domain_pure_api.js'
            if not checker.is_file():
                errors.append({'kind':'monitor_pure_domain_api_test_missing'})
            elif shutil.which('node'):
                cp=subprocess.run([shutil.which('node'),str(checker)],
                    capture_output=True,text=True,encoding='utf-8',
                    errors='replace',timeout=25)
                facts['pure_domain_api_test_rc']=cp.returncode
                if cp.returncode!=0:
                    errors.append({'kind':'monitor_pure_domain_api_test_failed',
                                   'details':(cp.stderr+cp.stdout)[-300:]})
        except Exception as exc:
            errors.append({'kind':'monitor_pure_domain_manifest_invalid',
                           'detail':str(exc)[:180]})

    solid_contract=root/'tools'/'check_monitor_solid_native_contract.py'
    if (root/'native/src/DesktopSolidColorSource.cs').is_file():
        if not solid_contract.is_file():
            errors.append({'kind':'native_solid_com_contract_check_missing'})
        else:
            verify=subprocess.run([sys.executable,str(solid_contract),'--root',str(root)],
                capture_output=True,text=True,encoding='utf-8',
                errors='replace',timeout=75)
            facts['native_solid_com_test_rc']=verify.returncode
            if verify.returncode!=0:
                errors.append({'kind':'native_solid_com_contract_failed',
                               'detail':(verify.stderr+verify.stdout)[-350:]})

    correlation_contract=root/'tools'/'check_monitor_native_request_correlation.py'
    if not correlation_contract.is_file():
        errors.append({'kind':'native_request_correlation_check_missing'})
    else:
        verify=subprocess.run([sys.executable,str(correlation_contract),'--root',str(root)],
            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=75)
        facts['native_request_correlation_test_rc']=verify.returncode
        if verify.returncode!=0:
            errors.append({'kind':'native_request_correlation_failed',
                           'detail':(verify.stderr+verify.stdout)[-500:]})

    # One owner for generation/attention state logic, with injected read-only
    # data sources and a separate focused contract regression.
    node_gen = ext/'monitor-node-generation-state.js'
    html_source=(ext/'desktop.html').read_text(encoding='utf-8')
    if node_gen.is_file():
        script_tag='<script src="monitor-node-generation-state.js"></script>'
        owner_test=root/'tools'/'check_monitor_node_generation_state.js'
        if script_tag not in html_source or html_source.index(script_tag)>=html_source.index('<script src="monitor.js"></script>'):
            errors.append({'kind':'node_generation_module_script_load_order_invalid'})
        if not owner_test.is_file():
            errors.append({'kind':'node_generation_state_contract_test_missing'})
        elif shutil.which('node'):
            outcome=subprocess.run([shutil.which('node'),str(owner_test)],
               capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=25)
            facts['node_generation_state_test_rc']=outcome.returncode
            if outcome.returncode:
                errors.append({'kind':'node_generation_state_contract_regression',
                  'detail':(outcome.stdout+outcome.stderr)[-450:]})

    # Exact Monitor host-identity fallback is a separate bounded dependency.
    host_script=ext/'monitor-host-window-identity.js'
    if host_script.is_file():
        html=(ext/'desktop.html').read_text(encoding='utf-8')
        host_tag='<script src="monitor-host-window-identity.js"></script>'
        monitor_tag='<script src="monitor.js"></script>'
        if host_tag not in html or monitor_tag not in html or html.index(host_tag)>html.index(monitor_tag):
            errors.append({'kind':'monitor_host_identity_script_load_order_invalid'})
        host_test=root/'tools'/'check_monitor_host_window_identity.js'
        if not host_test.is_file():
            errors.append({'kind':'monitor_host_identity_regression_test_missing'})
        elif shutil.which('node'):
            c=subprocess.run([shutil.which('node'),str(host_test)],
                capture_output=True,text=True,encoding='utf-8',
                errors='replace',timeout=25)
            facts['monitor_host_identity_test_rc']=c.returncode
            if c.returncode!=0:
                errors.append({'kind':'monitor_host_identity_regression_failed',
                               'detail':(c.stdout+c.stderr)[-360:]})

    monitor = ext/'monitor.js'
    index = ext/'MONITOR_JS_INDEX.md'
    if monitor.exists() and index.exists():
        monitor_hash = sha256(monitor)
        text = index.read_text(encoding='utf-8', errors='replace')
        m = re.search(r'^- sha256: `([0-9a-f]{64})`$', text, re.M)
        index_hash = m.group(1) if m else None
        facts['monitor_js_sha256'] = monitor_hash
        facts['index_sha256'] = index_hash
        if index_hash != monitor_hash:
            errors.append({'kind':'stale_function_index','monitor':monitor_hash,'index':index_hash})

    html = ext/'desktop.html'
    loaded_js = set()
    if html.exists():
        t = html.read_text(encoding='utf-8', errors='replace')
        scripts = re.findall(r'<script\s+src="([^"]+)"', t)
        stylesheets = re.findall(r'<link\s+[^>]*href="([^"]+\.css(?:\?[^"#]*)?)"', t)
        loaded_js.update(s.split('?')[0] for s in scripts)
        missing_scripts = [s for s in scripts if not (ext/s.split('?')[0]).exists()]
        missing_stylesheets = [s for s in stylesheets if not (ext/s.split('?')[0]).exists()]
        facts['desktop_scripts'] = scripts
        facts['desktop_stylesheets'] = stylesheets
        if missing_scripts: errors.append({'kind':'missing_script','scripts':missing_scripts})
        if missing_stylesheets: errors.append({'kind':'missing_stylesheet','stylesheets':missing_stylesheets})
        if 'monitor-provider-launch-queue.js' not in scripts:
            errors.append({'kind':'provider_queue_not_loaded'})
        if 'monitor-act-transport.js' not in scripts:
            errors.append({'kind':'act_transport_not_loaded'})
        else:
            monitor_script = next((s for s in scripts if s.startswith('monitor.js')), None)
            if monitor_script and scripts.index('monitor-act-transport.js') > scripts.index(monitor_script):
                errors.append({'kind':'act_transport_loaded_after_monitor'})
        if 'monitor-naver-launch-queue.js' in scripts:
            errors.append({'kind':'legacy_provider_queue_name_loaded'})

        monitor_text = (ext/'monitor.js').read_text(encoding='utf-8', errors='replace') if (ext/'monitor.js').exists() else ''
        layout_js = (ext/'monitor-ui-layout.js').read_text(encoding='utf-8', errors='replace') if (ext/'monitor-ui-layout.js').exists() else ''
        layout_css = (ext/'monitor-ui-layout.css').read_text(encoding='utf-8', errors='replace') if (ext/'monitor-ui-layout.css').exists() else ''
        if 'MonitorUiLayout' in monitor_text and 'chooseCaptureView' in monitor_text:
            monitor_script = next((s for s in scripts if s.split('?')[0] == 'monitor.js'), None)
            layout_script = next((s for s in scripts if s.split('?')[0] == 'monitor-ui-layout.js'), None)
            contract = {
                'layout_script_loaded_before_monitor': bool(
                    monitor_script and layout_script and scripts.index(layout_script) < scripts.index(monitor_script)),
                'choose_capture_view_declared': bool(re.search(
                    r'function\s+chooseCaptureView\s*\(', layout_js)),
                'choose_capture_view_exported': bool(re.search(
                    r'MonitorUiLayout\s*=\s*Object\.freeze\([^)]*chooseCaptureView', layout_js, re.S)),
                'layout_stylesheet_loaded': any(
                    s.split('?')[0] == 'monitor-ui-layout.css' for s in stylesheets),
                'capture_age_label_styled': '.monitor-window-capture-age-label' in layout_css,
                'stale_capture_styled': '.monitor-window-capture-stale' in layout_css,
                'renderer_has_nonthrowing_fallback': bool(re.search(
                    r'function\s+monitorChooseCaptureView\s*\([\s\S]*?typeof\s+chooser\s*===\s*"function"',
                    monitor_text)),
            }
            facts['monitor_ui_layout_dependency_contract'] = contract
            broken = [name for name, present in contract.items() if not present]
            if broken:
                errors.append({
                    'kind':'monitor_ui_layout_dependency_contract_broken',
                    'missing':broken,
                })

    manifest = ext/'manifest.json'
    if manifest.exists():
        try:
            manifest_obj = json.loads(manifest.read_text(encoding='utf-8-sig'))
            worker = (manifest_obj.get('background') or {}).get('service_worker')
            if worker:
                loaded_js.add(worker)
            for item in manifest_obj.get('content_scripts') or []:
                loaded_js.update(item.get('js') or [])
        except Exception as e:
            errors.append({'kind':'extension_manifest_invalid','path':str(manifest),'error':str(e)})

    node = shutil.which('node')
    facts['node_executable'] = node
    if node:
        thumbnail_checks = [
            root/'tools'/'check_monitor_thumbnail_architecture.js',
            root/'tools'/'check_monitor_thumbnail_v2_cleanroom.js',
            root/'tools'/'check_monitor_thumbnail_v2_native_ports.js',
            root/'tools'/'check_monitor_thumbnail_v2_render_ownership.js',
        ]
        for checker in thumbnail_checks:
            if not checker.is_file():
                errors.append({'kind':'monitor_thumbnail_contract_test_missing','path':str(checker)})
                continue
            checked=subprocess.run([node,str(checker)],cwd=str(root.parent.parent),
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            facts['thumbnail_test_'+checker.stem]=checked.returncode
            if checked.returncode:
                errors.append({'kind':'monitor_thumbnail_contract_regression','name':checker.name,
                    'detail':(checked.stdout+checked.stderr)[-600:]})
    js_syntax = {}
    if not node:
        errors.append({'kind':'js_syntax_checker_missing','executable':'node'})
    else:
        for name in sorted(loaded_js):
            js_path = ext / name
            if js_path.suffix.lower() != '.js' or not js_path.exists():
                continue
            try:
                js_run = subprocess.run(
                    [node, '--check', str(js_path)],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=20,
                )
                js_syntax[name] = js_run.returncode
                if js_run.returncode != 0:
                    errors.append({
                        'kind':'js_syntax_failed',
                        'path':str(js_path),
                        'returncode':js_run.returncode,
                        'stderr':js_run.stderr[-4000:],
                    })
            except Exception as e:
                js_syntax[name] = None
                errors.append({'kind':'js_syntax_check_error','path':str(js_path),'error':str(e)})
    facts['js_syntax_check_rc'] = js_syntax

    top_level_js = sorted(p.name for p in ext.glob('*.js') if p.is_file())
    orphan_js = sorted(name for name in top_level_js if name not in loaded_js)
    facts['top_level_js'] = top_level_js
    facts['loaded_js'] = sorted(loaded_js)
    if orphan_js:
        errors.append({'kind':'unreferenced_top_level_js','files':orphan_js})

    css_path = ext/'monitor.css'
    if css_path.exists():
        css_text = css_path.read_text(encoding='utf-8', errors='replace')
        monitor_text = monitor.read_text(encoding='utf-8', errors='replace') if monitor.exists() else ''
        # Same-tab chat changes are an explicit user-decision flow.  Keep its
        # controls distinct from ordinary node discovery: restore is orange,
        # approve is green, and both remain in the row's right-side status area.
        recovery_contract = {
            'chat_changed_branch': 'nodeLocationState?.status === "CHAT_CHANGED"' in monitor_text,
            'restore_then_approve': 'changeControls.append(restore,approve); status.append(changeControls);' in monitor_text,
            'right_status_layout': bool(re.search(r'\.monitor-worker-row\s*\{[^}]*justify-content:\s*space-between', css_text, re.S)),
            'right_control_layout': bool(re.search(r'\.monitor-node-chat-change-controls\s*\{[^}]*justify-content:\s*flex-end', css_text, re.S)),
            'approve_green': bool(re.search(r'\.monitor-node-chat-change-controls\s+\.monitor-node-approve\s*\{[^}]*color:\s*#bdf3ce', css_text, re.S)),
            'restore_orange': bool(re.search(r'\.monitor-node-chat-change-controls\s+\.monitor-node-restore\s*\{[^}]*color:\s*#ffe0a2', css_text, re.S)),
        }
        facts['chat_change_recovery_contract'] = recovery_contract
        missing_contract = [name for name, present in recovery_contract.items() if not present]
        if missing_contract:
            errors.append({'kind':'chat_change_recovery_contract_broken','missing':missing_contract})
        individual_recovery_start = monitor_text.find('async function restoreMonitorDetachedTask(')
        individual_recovery_end = monitor_text.find('\nasync function ', individual_recovery_start + 1)
        individual_recovery_text = monitor_text[individual_recovery_start:individual_recovery_end if individual_recovery_end >= 0 else None]
        individual_recovery_contract = {
            'exact_conversation_launch': 'restoreChatGptConversation' in individual_recovery_text,
            'duplicate_open_rejected': 'alreadyOpen.length>1' in individual_recovery_text,
            'old_node_binding_not_copied': 'monitorStoreNodeBinding' not in individual_recovery_text,
        }
        facts['individual_recovery_contract'] = individual_recovery_contract
        missing_individual_contract = [name for name, present in individual_recovery_contract.items() if not present]
        if missing_individual_contract:
            errors.append({'kind':'individual_recovery_contract_broken','missing':missing_individual_contract})
        panel_z_match = re.search(r'monitorStructurePanel\.style\.cssText="[^"]*z-index:(\d+)', monitor_text)
        ghost_block_match = re.search(r'\.monitor-node-drag-ghost\s*\{([^}]*)\}', css_text, re.S)
        ghost_z_match = re.search(r'z-index:\s*(\d+)', ghost_block_match.group(1) if ghost_block_match else '')
        org_ghost_block_match = re.search(r'\.monitor-org-drag-ghost\s*\{([^}]*)\}', css_text, re.S)
        panel_z = int(panel_z_match.group(1)) if panel_z_match else None
        ghost_z = int(ghost_z_match.group(1)) if ghost_z_match else None
        facts['structure_panel_z_index'] = panel_z
        facts['drag_ghost_z_index'] = ghost_z
        if panel_z is None or ghost_z is None:
            errors.append({'kind':'drag_ghost_layer_unresolved','panel_z':panel_z,'ghost_z':ghost_z})
        elif ghost_z <= panel_z:
            errors.append({'kind':'drag_ghost_layer_not_above_structure_panel','panel_z':panel_z,'ghost_z':ghost_z})
        if org_ghost_block_match and re.search(r'\bz-index\s*:', org_ghost_block_match.group(1)):
            errors.append({'kind':'drag_ghost_layer_split_ownership','selector':'.monitor-org-drag-ghost'})
        legacy_sketch_selectors = [
            x for x in ['.monitor-side-sketchpad', '.monitor-sketchpad-title']
            if x in css_text
        ]
        if legacy_sketch_selectors:
            warnings.append({'kind':'legacy_sketchpad_css_pending','selectors':legacy_sketch_selectors})

    bad_live = []
    if ext.exists():
        for p in ext.iterdir():
            n = p.name.lower()
            if p.is_file() and ('.bak' in n or n.endswith('.tmp') or 'patch-' in n):
                bad_live.append(p.name)
    if bad_live: errors.append({'kind':'live_extension_artifacts','files':bad_live})

    if (native/'live').exists():
        errors.append({'kind':'ambiguous_native_live_directory','path':str(native/'live')})

    manifests = [
        native/'com.pas40.desktop_window_monitor.json',
        native/'com.pas40.desktop_window_monitor_control.json',
    ]
    active = []
    for p in manifests:
        if not p.exists():
            errors.append({'kind':'native_manifest_missing','path':str(p)})
            continue
        try:
            obj = json.loads(p.read_text(encoding='utf-8-sig'))
            target = Path(obj.get('path',''))
            active.append(str(target))
            if not target.exists():
                errors.append({'kind':'native_target_missing','manifest':str(p),'target':str(target)})
        except Exception as e:
            errors.append({'kind':'native_manifest_invalid','path':str(p),'error':str(e)})
    facts['active_native_targets'] = active

    hist = root/'backup'/'native-history'
    facts['native_history_exists'] = hist.exists()
    if hist.exists() and not (hist/'README.md').exists():
        warnings.append({'kind':'native_history_missing_readme','path':str(hist)})

    org_checker = root/'tools'/'check_monitor_organization_model.py'
    if org_checker.exists():
        try:
            org_run = subprocess.run([sys.executable, str(org_checker), '--root', str(root)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            facts['organization_model_check_rc'] = org_run.returncode
            if org_run.returncode != 0:
                errors.append({'kind':'organization_model_check_failed','stdout':org_run.stdout[-6000:],'stderr':org_run.stderr[-2000:]})
        except Exception as e:
            errors.append({'kind':'organization_model_check_error','error':str(e)})

    result = {'ok':not errors,'errors':errors,'warnings':warnings,'facts':facts}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1

if __name__ == '__main__':
    raise SystemExit(main())
