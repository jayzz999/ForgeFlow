"""Security review for generated code."""

import re


async def review_code(code: str) -> dict:
    """Quick static security review of generated code."""
    issues = []

    # Check for hardcoded secrets
    secret_patterns = [
        (r'["\']sk-[a-zA-Z0-9]{20,}["\']', "Hardcoded OpenAI API key"),
        (r'["\']xoxb-[a-zA-Z0-9-]+["\']', "Hardcoded Slack bot token"),
        (r'["\']xapp-[a-zA-Z0-9-]+["\']', "Hardcoded Slack app token"),
        (r'password\s*=\s*["\'][^"\']+["\']', "Hardcoded password"),
        (r'api_key\s*=\s*["\'][a-zA-Z0-9]{10,}["\']', "Hardcoded API key"),
    ]

    for pattern, description in secret_patterns:
        if re.search(pattern, code):
            issues.append({"severity": "critical", "issue": description})

    # Check for dangerous operations
    danger_patterns = [
        (r'\bos\.system\b', "os.system call (use subprocess instead)"),
        (r'\beval\b\(', "eval() usage (code injection risk)"),
        (r'\bexec\b\(', "exec() usage (code injection risk)"),
        (r'__import__', "Dynamic import (potential injection)"),
        (r'\bshell\s*=\s*True\b', "shell=True in subprocess (injection risk)"),
    ]

    for pattern, description in danger_patterns:
        if re.search(pattern, code):
            issues.append({"severity": "warning", "issue": description})

    # Check for good practices
    checks = {
        "uses_env_vars": bool(re.search(r'os\.getenv|os\.environ', code)),
        "has_error_handling": bool(re.search(r'try:|except\s', code)),
        "has_logging": bool(re.search(r'import logging|logger\.|logging\.', code)),
        "has_timeout": bool(re.search(r'timeout', code)),
    }

    return {
        "safe": len([i for i in issues if i["severity"] == "critical"]) == 0,
        "issues": issues,
        "checks": checks,
        "summary": f"{len(issues)} issue(s) found" if issues else "Code passed security review",
    }
