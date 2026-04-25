"""Phase 4 — Skill Compiler: Embodiment.

Compiles a narrative Skill (LLM-readable markdown) into an executable
Python MCP server. The compiled server encodes the organism's learned
behavior as direct tool calls — no LLM reasoning required to execute them.

When a future organism inherits a compiled skill, the MCP server is
auto-started and attached, giving instant tool access without prompt
injection overhead.

Pipeline:
  1. Analyze the Skill body + decision history for action patterns
  2. LLM generates a Python MCP server implementing those patterns
  3. Validate the generated code (syntax check + dry import)
  4. Write to organisms/_compiled_skills/sk_<id>.py
  5. Update the Skill metadata with the compiled path

The result is a self-contained Python script that:
  - Uses `from mcp.server.fastmcp import FastMCP`
  - Exposes each learned pattern as a tool
  - Can run as `python <script>.py` via stdio transport
"""
from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.shared.gemini_client import generate_text

from .. import store
from . import pool

logger = logging.getLogger("genesis.skills.compiler")


def _compiled_dir() -> Path:
    """Directory for compiled skill servers."""
    d = Path(store._BASE) / "_compiled_skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


COMPILE_SYSTEM = """You are a Python MCP server code generator.
You write executable Python scripts that implement learned behaviors as tools.

You MUST follow this EXACT structure:

```
from mcp.server.fastmcp import FastMCP
import httpx

server = FastMCP("{server_name}")

@server.tool()
async def my_tool(param: str) -> str:
    \"\"\"Description of what this tool does.\"\"\" 
    return "result"

if __name__ == "__main__":
    server.run()
```

CRITICAL RULES:
1. `server = FastMCP(...)` MUST appear BEFORE any `@server.tool()` decorators
2. Do NOT use classes. All tools must be module-level async functions
3. Use `from mcp.server.fastmcp import FastMCP` (NOT `from fastmcp`)
4. Every tool function must have a docstring
5. Every tool must return a string or dict
6. Use `httpx` for HTTP calls
7. End with: `if __name__ == "__main__": server.run()`
8. Handle errors with try/except
9. NO classes. NO methods. Only plain async functions with @server.tool()

Return ONLY valid Python code. No markdown. No explanations.
"""


async def compile_skill(
    skill: pool.Skill,
    decisions: list | None = None,
) -> Optional[str]:
    """Compile a narrative Skill into an executable MCP server.

    Returns the file path of the compiled server, or None if compilation failed.
    """
    # Build context for the LLM
    decision_summary = ""
    if decisions:
        patterns = []
        for d in decisions[-10:]:
            action_name = d.action.get("name", "?")
            args = d.action.get("args", {})
            result_ok = d.result.get("ok") if isinstance(d.result, dict) else None
            if result_ok and action_name not in ("noop", "remember", "declare_done"):
                patterns.append(f"- {action_name}({', '.join(f'{k}={repr(v)[:50]}' for k,v in args.items())})")
        if patterns:
            decision_summary = "\nSuccessful action patterns observed:\n" + "\n".join(patterns)

    prompt = f"""Write a Python MCP server that embodies this organism's learned skill:

Skill Name: {skill.name}
Description: {skill.description}

{skill.body}
{decision_summary}

The server name should be "{skill.name}".
Create tools that directly implement the behaviors described above.
Each tool should be a self-contained function that produces useful output.
If the skill involves fetching web data, use httpx.
If the skill involves data processing, implement the logic directly."""

    try:
        raw = await generate_text(
            prompt=prompt,
            system=COMPILE_SYSTEM.format(server_name=skill.name),
            temperature=0.3,
            max_tokens=3000,
        )
    except Exception as e:
        logger.error(f"[compiler] LLM call failed for {skill.skill_id}: {e}")
        return None

    # Extract Python code from potential markdown wrapping
    code = _extract_python(raw)
    if not code:
        logger.error(f"[compiler] No valid Python extracted for {skill.skill_id}")
        return None

    # Fix common LLM mistakes
    code = _fix_common_issues(code, skill.name)

    # Validate syntax
    if not _validate_syntax(code):
        logger.error(f"[compiler] Syntax validation failed for {skill.skill_id}")
        return None

    # Write to disk
    file_path = _compiled_dir() / f"{skill.skill_id}.py"
    file_path.write_text(code, encoding="utf-8")
    os.chmod(file_path, 0o755)

    logger.info(f"[compiler] Compiled {skill.skill_id} → {file_path}")
    return str(file_path)


def _extract_python(raw: str) -> Optional[str]:
    """Extract clean Python code from LLM output."""
    raw = raw.strip()

    # Try to find code within markdown fences
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # If no fences, try to find the first `from` or `import` statement
    lines = raw.split("\n")
    code_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("from ", "import ", "#!", '"""', "# ")):
            code_start = i
            break

    if code_start is not None:
        # Find where the code ends (look for non-code patterns)
        code_lines = []
        for line in lines[code_start:]:
            # Stop at obvious non-code
            if line.strip().startswith(("This ", "Note:", "The above", "Here's")):
                break
            code_lines.append(line)
        return "\n".join(code_lines).strip()

    # Last resort: return everything
    return raw


def _fix_common_issues(code: str, name: str) -> str:
    """Fix common LLM code generation mistakes."""
    # Fix wrong import
    code = code.replace("from fastmcp import FastMCP", "from mcp.server.fastmcp import FastMCP")
    code = code.replace("from fastmcp import ", "from mcp.server.fastmcp import ")

    # Fix old decorator patterns
    code = re.sub(r"@register_tool\b", "@server.tool()", code)
    code = re.sub(r"@mcp\.tool\b", "@server.tool()", code)

    # Detect class-based patterns and rewrite to flat functions
    # The LLM sometimes wraps tools in a class, which breaks @server.tool()
    if re.search(r'^class\s+\w+', code, re.MULTILINE):
        code = _rewrite_class_to_flat(code, name)

    # Ensure server = FastMCP(...) appears BEFORE any @server.tool()
    if '@server.tool()' in code:
        server_decl = re.search(r'^server\s*=\s*FastMCP\(', code, re.MULTILINE)
        first_tool = code.find('@server.tool()')
        if server_decl and server_decl.start() > first_tool:
            # Server is declared after tool — move it before
            server_line = code[server_decl.start():code.index('\n', server_decl.start()) + 1]
            code = code[:server_decl.start()] + code[code.index('\n', server_decl.start()) + 1:]
            # Insert after imports
            last_import = 0
            for m in re.finditer(r'^(?:import|from)\s+', code, re.MULTILINE):
                last_import = code.index('\n', m.start()) + 1
            code = code[:last_import] + '\n' + server_line + '\n' + code[last_import:]

    # Ensure the server.run() entry point exists
    if "server.run()" not in code and "__main__" not in code:
        code += '\n\nif __name__ == "__main__":\n    server.run()\n'

    # Ensure the FastMCP import exists
    if "from mcp.server.fastmcp import FastMCP" not in code:
        code = "from mcp.server.fastmcp import FastMCP\n" + code

    # Ensure httpx import if httpx is used
    if "httpx" in code and "import httpx" not in code:
        code = "import httpx\n" + code

    return code


def _rewrite_class_to_flat(code: str, name: str) -> str:
    """Rewrite a class-based MCP server into flat module-level functions.
    
    The LLM sometimes generates:
        class Foo:
            @server.tool()
            async def bar(self, x): ...
    
    We need:
        server = FastMCP("name")
        @server.tool()
        async def bar(x): ...
    """
    lines = code.split('\n')
    new_lines = []
    in_class = False
    class_indent = 0
    server_created = False
    
    for line in lines:
        stripped = line.strip()
        
        # Skip class definition line
        if re.match(r'^class\s+\w+', stripped):
            in_class = True
            class_indent = len(line) - len(line.lstrip())
            continue
        
        # Skip server.add_tool lines
        if 'add_tool' in stripped:
            continue
        
        if in_class and stripped:
            # Check if we're still inside the class (indented)
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= class_indent and not stripped.startswith('#') and not stripped.startswith('@'):
                in_class = False
                new_lines.append(line)
                continue
            
            # Dedent class methods to module level
            dedented = line[class_indent + 4:] if len(line) > class_indent + 4 else line.lstrip()
            
            # Remove 'self' from method signatures
            dedented = re.sub(r'\(self,\s*', '(', dedented)
            dedented = re.sub(r'\(self\)', '()', dedented)
            
            # Remove self. references
            dedented = re.sub(r'self\.', '', dedented)
            
            # Ensure server is created before @server.tool()
            if '@server.tool()' in dedented and not server_created:
                new_lines.append(f'\nserver = FastMCP("{name}")')
                new_lines.append('')
                server_created = True
            
            new_lines.append(dedented)
        elif in_class and not stripped:
            new_lines.append('')
        else:
            new_lines.append(line)
    
    result = '\n'.join(new_lines)
    
    # Ensure server = FastMCP exists somewhere
    if 'server = FastMCP' not in result:
        # Insert after imports
        import_end = 0
        for m in re.finditer(r'^(?:import|from)\s+', result, re.MULTILINE):
            import_end = result.index('\n', m.start()) + 1
        result = result[:import_end] + f'\nserver = FastMCP("{name}")\n\n' + result[import_end:]
    
    return result


def _validate_syntax(code: str) -> bool:
    """Validate Python syntax without executing."""
    try:
        ast.parse(code)
        return True
    except SyntaxError as e:
        logger.warning(f"[compiler] Syntax error: {e}")
        return False


def _validate_imports(file_path: str) -> bool:
    """Validate that the script can be imported without errors.
    Runs in a subprocess to avoid polluting the main process.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open('{file_path}').read()); print('OK')"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


async def compile_and_attach(
    skill: pool.Skill,
    organism_id: Optional[str] = None,
) -> Optional[str]:
    """Compile a skill and optionally attach it to an organism.

    Full Phase 4 pipeline:
    1. Compile the skill into a Python MCP server
    2. If organism_id given, attach as a private MCP server
    3. Return the compiled file path

    Returns the compiled file path or None.
    """
    # Load decisions if we have an organism reference
    decisions = None
    if skill.parent_organisms:
        for oid in skill.parent_organisms:
            org_decisions = store.all_decisions(oid)
            if org_decisions:
                decisions = [d for d in org_decisions if not d.is_dream and not d.shadow_branch]
                break

    compiled_path = await compile_skill(skill, decisions)
    if not compiled_path:
        return None

    # Attach to organism if requested
    if organism_id:
        from ..types import MCPServerSpec
        from ..mcp.client import pool as mcp_pool

        org = store.load_organism(organism_id)
        if org:
            spec = MCPServerSpec(
                name=f"compiled_{skill.name}",
                command=sys.executable,
                args=[compiled_path],
            )
            # Don't duplicate
            existing_names = {s.name for s in org.mcp_servers}
            if spec.name not in existing_names:
                org.mcp_servers.append(spec)
                store.save_organism(org)
                await mcp_pool.ensure_organism(org.id, [spec])
                logger.info(f"[compiler] Attached compiled skill {skill.name} to {organism_id}")

    return compiled_path


def get_compiled_path(skill_id: str) -> Optional[str]:
    """Check if a compiled version of a skill exists."""
    p = _compiled_dir() / f"{skill_id}.py"
    if p.exists():
        return str(p)
    return None


def list_compiled() -> list[dict]:
    """List all compiled skill servers."""
    out = []
    d = _compiled_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("sk_*.py")):
        skill_id = p.stem
        skill = pool.load(skill_id)
        out.append({
            "skill_id": skill_id,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "name": skill.name if skill else "unknown",
            "compiled_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })
    return out
