import ast
import json
import re
from pathlib import Path

def analyze(root: Path):
    out = dict(languages=[], frameworks=[], files=[], functions=[], classes=[], imports=[], routes=[], tools=[], tests=[], entry_points=[], manifests=[], integrations=[], prompts=[], findings=[], warnings=['Static detections indicate source evidence, not working behavior. Secrets, generated folders and files above 2 MB are excluded. Dependency versions are not checked against a vulnerability database.'])
    imports = set()
    def finding(path, line, rule, severity, detail):
        out['findings'].append(dict(file=path, line=line, rule=rule, severity=severity, detail=detail))
    for file in sorted(root.rglob('*')):
        if not file.is_file():
            continue
        rel = file.relative_to(root).as_posix()
        out['files'].append(rel)
        ext = file.suffix.lower()
        if file.name in ('requirements.txt','pyproject.toml','package.json','Pipfile','poetry.lock','package-lock.json','yarn.lock'):
            out['manifests'].append(rel)
        if ext not in ('.py','.js','.ts','.tsx','.jsx','.json','.txt','.md','.toml'):
            continue
        source = file.read_text(encoding='utf-8', errors='replace').lstrip("\ufeff")
        if file.name.startswith('test_') or '.test.' in file.name or '.spec.' in file.name:
            out['tests'].append(rel)
        if 'prompt' in file.stem.lower():
            out['prompts'].append({'file':rel,'evidence':'Filename suggests a prompt; unverified'})
        if ext == '.py':
            out['languages'].append('Python')
            try:
                tree = ast.parse(source, filename=rel)
            except (SyntaxError, RecursionError) as exc:
                finding(rel, getattr(exc,'lineno',0), 'syntax', 'high', 'Python parsing failed; inspect source locally')
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    out['classes' if isinstance(node,ast.ClassDef) else 'functions'].append({'name':node.name,'file':rel,'line':node.lineno})
                    for dec in node.decorator_list:
                        expression = ast.unparse(dec)
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ('get','post','put','delete','patch','route'):
                            route = dec.args[0].value if dec.args and isinstance(dec.args[0],ast.Constant) and isinstance(dec.args[0].value,str) else '(dynamic)'
                            out['routes'].append({'file':rel,'line':node.lineno,'method':dec.func.attr,'path':route})
                        if re.search(r'\btool\b', expression):
                            out['tools'].append({'file':rel,'name':node.name,'line':node.lineno})
                if isinstance(node, ast.Import):
                    imports.update(n.name.split('.')[0] for n in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split('.')[0])
                if isinstance(node, ast.ExceptHandler) and (node.type is None or (isinstance(node.type,ast.Name) and node.type.id in ('Exception','BaseException'))):
                    finding(rel,node.lineno,'broad-exception','low','Broad exception handler may hide failures; inspect intended recovery.')
                if isinstance(node,ast.Call):
                    name = ast.unparse(node.func)
                    if name in ('eval','exec','os.system','pickle.loads','pickle.load'):
                        finding(rel,node.lineno,'unsafe-call','high',f'Potentially unsafe call: {name}; data flow requires review.')
                    if any(k.arg == 'shell' and isinstance(k.value,ast.Constant) and k.value.value is True for k in node.keywords):
                        finding(rel,node.lineno,'shell-execution','high','Subprocess shell=True requires input validation.')
            if '__name__' in source and '__main__' in source:
                out['entry_points'].append({'file':rel,'evidence':'Main guard observed'})
        elif ext in ('.js','.jsx','.ts','.tsx'):
            out['languages'].append('TypeScript' if ext in ('.ts','.tsx') else 'JavaScript')
            if re.search(r"(?:require\(|from\s*)['\"]express['\"]", source):
                imports.add('express')
            for match in re.finditer(r'\b(?:app|router)\.(get|post|put|delete)\s*\(',source):
                out['routes'].append({'file':rel,'line':source[:match.start()].count('\n')+1,'method':match.group(1),'path':'JS route candidate; parser unavailable'})
        if file.name == 'package.json':
            try:
                package = json.loads(source)
                imports.update(package.get('dependencies',{}))
                out['package_scripts'] = list(package.get('scripts',{}))
            except (ValueError,TypeError):
                out['warnings'].append(f'Invalid package manifest: {rel}')
        if re.search(r'(?i)(api_key|password|secret|token)\s*[:=]\s*[\"\'][^\"\']{8,}[\"\']', source):
            finding(rel,0,'possible-secret','high','Potential hardcoded credential; value deliberately omitted.')
    out['imports'] = sorted(imports)
    out['languages'] = sorted(set(out['languages']))
    out['frameworks'] = sorted(imports & {'fastapi','flask','django','express','next','streamlit'})
    out['integrations'] = sorted(imports & {'openai','anthropic','langchain','llama_index','chromadb','faiss','sqlite3','sqlalchemy','pymongo','psycopg2'})
    out['architecture_summary'] = f"Observed {len(out['files'])} files, {len(out['functions'])} Python functions, {len(out['routes'])} route candidates and {len(out['tests'])} test files. Framework evidence: {', '.join(out['frameworks']) or 'none'}. No uploaded code was executed."
    return out


