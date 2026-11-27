"""Run the ACTUAL NuSMV/nuXmv binary; never substitute Python outcomes."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from protocol import EXPECTED,PROPERTIES,models
from smv import render

HERE=Path(__file__).resolve().parent


def find_binary(explicit=None):
    if explicit:
        found=shutil.which(explicit)
        if found:return found
        path=Path(explicit)
        if path.is_file():return str(path.resolve())
        return None
    for name in ['NuSMV','nusmv','nuXmv','nuxmv']:
        found=shutil.which(name)
        if found:return found
    return None


def parse_result(stdout):
    matches=re.findall(r'^\s*--\s+specification\b.*\bis\s+(true|false)\s*$',stdout,re.MULTILINE)
    if len(matches)!=1:raise ValueError(f'expected exactly one completed property verdict, got {len(matches)}')
    return matches[0]=='true'


def run(binary=None,out=None,timeout=30):
    out=Path(out) if out else HERE/'generated/nusmv'
    out.mkdir(parents=True,exist_ok=True)
    executable=find_binary(binary)
    if executable is None:
        report={'status':'not_run','reason':'NuSMV/nuXmv executable not installed or not found',
                'binary_requested':binary,'results':[],
                'note':'Python results are separate and are NOT NuSMV results.'}
        (out/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        (out/'NOT_RUN.txt').write_text(report['reason']+'\n',encoding='utf-8')
        return report
    (out/'NOT_RUN.txt').unlink(missing_ok=True)
    try:
        version=subprocess.run([executable,'-h'],capture_output=True,text=True,timeout=timeout)
        (out/'tool_help_and_version.log').write_text(version.stdout+version.stderr,encoding='utf-8')
    except (OSError,subprocess.TimeoutExpired) as exc:
        (out/'tool_help_and_version.log').write_text(str(exc)+'\n',encoding='utf-8')
    results=[]
    for model in models():
        directory=out/model['name'];directory.mkdir(exist_ok=True)
        for index,prop in enumerate(PROPERTIES):
            path=(directory/(prop['id']+'.smv')).resolve()
            path.write_text(render(model,[prop]),encoding='utf-8')
            command=[executable,'-ctt',str(path)]
            start=time.perf_counter()
            record={'model':model['name'],'property':prop['id'],'formula':prop['formula'],
                    'expected':EXPECTED[model['name']][index],'command':command,
                    'method':'NuSMV/nuXmv default complete symbolic checking; no -bmc, fairness or state restriction'}
            try:
                process=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
                record['wall_seconds']=time.perf_counter()-start
                record['exit_code']=process.returncode
                (directory/(prop['id']+'.stdout.log')).write_text(process.stdout,encoding='utf-8')
                (directory/(prop['id']+'.stderr.log')).write_text(process.stderr,encoding='utf-8')
                verdict=parse_result(process.stdout)
                record['actual']=verdict
                record['passed']=process.returncode==0 and verdict==record['expected']
            except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
                record['wall_seconds']=time.perf_counter()-start
                record['passed']=False;record['error']=str(exc)
            results.append(record)
    report={'status':'passed' if all(r['passed'] for r in results) else 'failed',
            'binary':executable,'property_runs':len(results),'results':results}
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Run real NuSMV/nuXmv and compare all 30 verdicts with expected values')
    parser.add_argument('--binary',help='Path/name of an installed NuSMV or nuXmv executable')
    parser.add_argument('--out',default=str(HERE/'generated/nusmv'))
    parser.add_argument('--allow-missing',action='store_true',help='Return success on missing tool, but keep explicit NOT RUN status')
    args=parser.parse_args(argv)
    report=run(args.binary,args.out)
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False,indent=2))
    if report['status']=='not_run':return 0 if args.allow_missing else 2
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
