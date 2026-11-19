"""Compare fixtures with manually specified diagnostics; also run independent units."""
import json
import unittest
from pathlib import Path

from main import compile_source, diagnostic_dict

HERE = Path(__file__).resolve().parent


def run_fixtures():
    manifest = json.loads((HERE/'tests/manifest.json').read_text(encoding='utf-8'))
    results = []
    for case in manifest:
        source = (HERE/'tests'/(case['name']+'.funny')).read_text(encoding='utf-8')
        program, diagnostics = compile_source(source)
        actual = [diagnostic_dict(d)['code'] for d in diagnostics]
        passed = actual == case['expected']
        expected_dir = HERE/'tests/expected'
        if case['expected']:
            snapshot = '\n'.join(map(str, diagnostics)) + '\n'
            expected_file = expected_dir/(case['name']+'.err')
        else:
            from funny_ast import to_json
            snapshot = to_json(program)+'\n'
            expected_file = expected_dir/(case['name']+'.json')
        if expected_file.exists():
            passed = passed and expected_file.read_text(encoding='utf-8') == snapshot
        else:
            passed = False
        passed = passed and all(d.line > 0 and d.col > 0 for d in diagnostics)
        results.append({'name': case['name'], 'expected_codes': case['expected'],
                        'actual_codes': actual, 'passed': passed})
        print(f"{'PASS' if passed else 'FAIL'} {case['name']}" + ('' if passed else f" expected={case['expected']} actual={actual}"))
    return results


def main():
    results = run_fixtures()
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern='test_semantic.py')
    units = unittest.TextTestRunner(verbosity=2).run(suite)
    payload = {'fixture_total': len(results), 'fixture_passed': sum(r['passed'] for r in results),
               'unit_total': units.testsRun, 'unit_failed': len(units.failures)+len(units.errors),
               'fixtures': results}
    out = HERE/'generated'
    out.mkdir(exist_ok=True)
    (out/'test_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Fixtures: {payload['fixture_passed']}/{len(results)}; unit tests: {units.testsRun}")
    return 0 if all(r['passed'] for r in results) and units.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
