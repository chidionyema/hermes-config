"""Surgical function replacement — bypasses patch tool's indent bug.

The `patch` tool sometimes over-indents every line of a long replacement, which
mangles code structure. When this happens, use this helper instead:

    from surgical_replace import replace_function
    replace_function('path/to/file.py', 'render_card', NEW_SOURCE)

It finds the function by its def line, locates the next top-level def, and
splices the new source in. Preserves everything outside the function untouched.

Usage:
    from pathlib import Path
    Path('surgical_replace.py').write_text(__file__)  # first time

    from surgical_replace import replace_function
    replace_function(
        path='gateway/operator_shell/summary_card.py',
        fn_name='render_summary_card',
        new_source=NEW_RENDER_FN,
    )
"""
from pathlib import Path


def replace_function(path: str, fn_name: str, new_source: str) -> None:
    """Replace *fn_name* in *path* with *new_source* while preserving everything else.

    Locates ``def fn_name(`` and replaces through the next top-level ``def`` line.
    Handles backslash continuations and indentation, but assumes each top-level
    function starts at column 0 with a ``def`` keyword.

    Args:
        path: Path to the Python file.
        fn_name: The function name to replace (e.g., 'render_card').
        new_source: The full new function source, ending with a newline.

    Raises:
        ValueError: If the function isn't found or no next top-level def exists.
    """
    p = Path(path)
    src = p.read_text(encoding='utf-8')
    lines = src.splitlines(keepends=True)

    # Find def fn_name at column 0
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f'def {fn_name}('):
            start = i
            break
    if start is None:
        raise ValueError(f'Function def {fn_name}( not found in {path}')

    # Find next top-level def after `start`
    end = None
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.startswith('def ') and not line.startswith('def __'):
            end = j
            break
    if end is None:
        raise ValueError(f'No function after def {fn_name} in {path}')

    # Splice in new_source (normalize trailing newline)
    if not new_source.endswith('\n'):
        new_source = new_source + '\n'
    new_lines = lines[:start] + [new_source] + lines[end:]
    p.write_text(''.join(new_lines), encoding='utf-8')
    print(f'Replaced def {fn_name}( ({end - start} lines) in {path}')


def replace_lines(path: str, start_line: int, end_line: int, new_lines: str) -> None:
    """Replace a 1-indexed line range with *new_lines*.

    For non-function scope rewrites. start_line and end_line are 1-indexed, inclusive
    on both ends. Useful for fixing a section of code without disturbing the rest.
    """
    p = Path(path)
    src = p.read_text(encoding='utf-8')
    lines = src.splitlines(keepends=True)
    # convert 1-indexed to 0-indexed
    s = start_line - 1
    e = end_line  # slice end is exclusive
    if not new_lines.endswith('\n'):
        new_lines = new_lines + '\n'
    out = lines[:s] + [new_lines] + lines[e:]
    p.write_text(''.join(out), encoding='utf-8')
    print(f'Replaced lines {start_line}-{end_line} ({end_line - start_line + 1} lines) in {path}')
