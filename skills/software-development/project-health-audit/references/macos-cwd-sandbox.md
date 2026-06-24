# macOS Sandbox CWD Permission Failures in Audit Scripts

When the Hermes terminal backend lacks Full Disk Access (FDA) permission for
directories like `~/Documents/code/` or `~/code/`, subprocess-based audit
scripts encounter cryptic failures that look like missing paths but aren't.

## Root Cause

macOS sandboxing: `os.path.exists(dir)` returns `True` and `os.path.isdir(dir)`
returns `True`, but the process can't resolve `getcwd()` or `readdir()` inside
the directory. Different tools surface this differently:

| Tool | Error message | Exit code |
|------|--------------|-----------|
| `uv run` | `Current directory does not exist` | 1 |
| `.venv/bin/python` | `realpath: .venv/bin/: Operation not permitted` | 1 |
| `npm` | `EPERM: process.cwd failed with error operation not permitted, uv_cwd` | 7 |
| `pytest` (via uv) | `Current directory does not exist` | 0 (!) |
| `npm test` / `npm run build` | May succeed (exit 0) despite shell-init noise | 0 |

Note: `uv run pytest` exits **0** with "Current directory does not exist" —
this is a **false pass** that must be detected in output, not just exit code.

## Fix Pattern (Three Parts)

### 1. Probe CWD with subprocess, not os.listdir

`os.listdir(path)` fails with `PermissionError` even though `subprocess.Popen(cwd=path)`
can work. Use a lightweight subprocess probe:

```python
def cwd_usable(path):
    if path is None:
        return True
    if not path.exists():
        return False
    if not path.is_dir():
        return False
    try:
        result = subprocess.run(
            ["true"], capture_output=True, timeout=5,
            cwd=str(path),
        )
        return result.returncode == 0
    except Exception:
        return False
```

### 2. Filter Shell-Init Noise from stderr

When using `shell=True` in `subprocess.Popen(cwd=path)`, `/bin/sh` emits
initialization errors on stderr that are NOT from the actual command:

```
shell-init: error retrieving current directory: getcwd: cannot access parent directories: Operation not permitted
chdir: error retrieving current directory: getcwd: cannot access parent directories: Operation not permitted
```

Strip these before any output analysis:

```python
_SHELL_NOISE_PATTERNS = [
    "shell-init: error retrieving current directory",
    "chdir: error retrieving current directory",
]
clean_out = out
clean_err = err
for pat in _SHELL_NOISE_PATTERNS:
    clean_out = "\n".join(
        line for line in clean_out.split("\n") if pat not in line
    )
    clean_err = "\n".join(
        line for line in clean_err.split("\n") if pat not in line
    )
```

### 3. Skip, Don't Fail, on CWD/Permission Errors

Detect CWD errors in cleaned command output. For exit code 0 (false pass) AND
for exit code != 0 (genuine failure whose root cause is CWD inaccessibility):

```python
false_pass_markers = [
    "current directory does not exist",
    "operation not permitted",
    "permissionerror",
]
combined_clean = (clean_out + clean_err).lower()

# False-pass: exit 0 but output shows CWD error
if code == 0 and any(m in combined_clean for m in false_pass_markers):
    state = "skipped"
    # ... skip, don't pass

# CWD failure: exit != 0 but root cause is permissions
if code != 0 and any(m in combined_clean for m in false_pass_markers):
    state = "skipped"
    # ... skip, don't fail
```

## Additional Pre-Flight Checks

For specific tools that are known to be sensitive to CWD permissions:

### .venv/bin/python

```python
def _venv_python_ok(project_path):
    venv_python = project_path / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return False
    if not os.access(str(venv_python), os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(venv_python), "--version"],
            capture_output=True, text=True, timeout=10,
            cwd=str(project_path),
        )
        return result.returncode == 0
    except Exception:
        return False
```

### npm auth

```python
def _npm_auth_ok():
    try:
        result = subprocess.run(
            ["npm", "whoami"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False
```

## Verdict Logic

Skipped checks (state=`"skipped"`) should NOT fail the audit. The verdict should
be PASS when there are no real failures, with skipped count noted:

```
INTEGRITY VERDICT: PASS — 3/9 checks passed (6 skipped — cwd/venv/auth not available)
```

Only `missing` (required) and `fail` (required) states should produce a FAIL verdict.

## Testing

Run the audit script from a directory that doesn't trigger the permission issue
to isolate the subprocess behavior from the calling shell:

```bash
cd /tmp && python3 /path/to/audit-script.py
```
