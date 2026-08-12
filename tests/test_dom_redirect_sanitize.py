import os, shutil, subprocess, sys, unittest

JS_PATH = os.path.join(os.path.dirname(__file__), '..', 'server', 'static', 'js', 'utils.js')


def run_node_assertions():
    """Execute the sanitizer functions inside Node against utils.js content.

    Loads utils.js in a Node VM, then asserts the sanitizer behaviour. Returns
    (returncode, stdout) so failures surface as an assertion with output.
    """
    script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(src, ctx);
const { safeDateParam, safeAgentId } = ctx;

const cases = [];
function check(name, got, want) {
    cases.push(got === want ? `PASS ${name}` : `FAIL ${name}: got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
}

// safeDateParam
check('safeDateParam valid', safeDateParam("2026-08-10"), "2026-08-10");
check('safeDateParam script payload', safeDateParam("<script>alert(1)</script>"), "");
check('safeDateParam javascript url', safeDateParam("javascript:alert(1)"), "");
check('safeDateParam traversal', safeDateParam("../../etc/passwd"), "");
check('safeDateParam empty', safeDateParam(""), "");
check('safeDateParam null', safeDateParam(null), "");
check('safeDateParam undefined', safeDateParam(undefined), "");

// safeAgentId
check('safeAgentId valid uuid', safeAgentId("123e4567-e89b-12d3-a456-426614174000"), "123e4567-e89b-12d3-a456-426614174000");
check('safeAgentId script payload', safeAgentId("<script>alert(1)</script>"), "");
check('safeAgentId path traversal', safeAgentId("../../agents"), "");
check('safeAgentId too short', safeAgentId("abc"), "");
check('safeAgentId empty', safeAgentId(""), "");

console.log(cases.join('\n'));
if (cases.some(c => c.startsWith('FAIL'))) process.exit(1);
"""
    r = subprocess.run(['node', '-e', script, JS_PATH], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@unittest.skipUnless(shutil.which('node'), "Node.js not available")
class TestDomRedirectSanitize(unittest.TestCase):
    def test_sanitizers_reject_payloads(self):
        rc, out = run_node_assertions()
        self.assertEqual(rc, 0, f"Node assertions failed:\n{out}")
        self.assertNotIn("FAIL", out, f"Sanitizer failed:\n{out}")
        self.assertIn("PASS safeDateParam valid", out)
        self.assertIn("PASS safeAgentId valid uuid", out)


if __name__ == "__main__":
    unittest.main()
