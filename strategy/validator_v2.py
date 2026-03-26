"""AST-based validation of V2 strategy code — enforces main(data) interface.

Code is NEVER executed during validation. Only parsed and inspected.
"""

import ast
import logging

from shared.schemas import ValidationResult

logger = logging.getLogger(__name__)

# Allowed imports for strategy main() code (no network, no OS)
ALLOWED_IMPORTS = {
    # Python stdlib
    "math", "statistics", "collections", "itertools", "functools",
    "datetime", "decimal", "typing", "logging",
    # Data science
    "numpy", "pandas",
}

FORBIDDEN_NAMES = {
    "os", "sys", "subprocess", "importlib", "eval", "exec",
    "open", "__import__", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "breakpoint",
    "requests", "urllib", "socket", "http",
}


def validate_strategy_code(source: str, data_config: dict | None = None) -> ValidationResult:
    """Validate V2 strategy code. Returns ValidationResult.

    Args:
        source: Python source code containing a main(data) function.
        data_config: Optional data config dict with field names and lookbacks.
                     Used to check data key access and index bounds.
    """
    result = ValidationResult()

    # 1. Parse
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        result.add_error(f"Syntax error at line {e.lineno}: {e.msg}")
        return result

    # 2. Check imports
    _check_imports(tree, result)

    # 3. Check for forbidden names
    _check_forbidden_names(tree, result)

    # 4. Find main() function
    main_funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
    ]

    if len(main_funcs) == 0:
        result.add_error(
            "Must define a function named 'main'. "
            "Example: def main(data: dict) -> np.ndarray:"
        )
        return result

    if len(main_funcs) > 1:
        result.add_error(
            f"Found {len(main_funcs)} functions named 'main' — must have exactly one."
        )
        return result

    main_func = main_funcs[0]

    # 5. Must NOT be async (numpy operations are synchronous)
    if isinstance(main_func, ast.AsyncFunctionDef):
        result.add_error("'main' must be a regular function (not async).")

    # 6. Check parameters — must have exactly one: 'data'
    args = [a.arg for a in main_func.args.args]
    if args != ["data"]:
        result.add_error(
            f"'main' must take exactly one parameter named 'data', got ({', '.join(args)})"
        )

    # 7. Check data key access if data_config provided
    if data_config and result.valid:
        _check_data_access(main_func, data_config, result)

    return result


def _check_imports(tree: ast.AST, result: ValidationResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS and alias.name not in ALLOWED_IMPORTS:
                    result.add_error(
                        f"Line {node.lineno}: Import '{alias.name}' is not allowed. "
                        f"Allowed: {', '.join(sorted(ALLOWED_IMPORTS))}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root not in ALLOWED_IMPORTS and node.module not in ALLOWED_IMPORTS:
                    result.add_error(
                        f"Line {node.lineno}: Import from '{node.module}' is not allowed. "
                        f"Allowed: {', '.join(sorted(ALLOWED_IMPORTS))}"
                    )


def _check_forbidden_names(tree: ast.AST, result: ValidationResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            result.add_error(
                f"Line {node.lineno}: Use of '{node.id}' is forbidden for security."
            )
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            result.add_error(
                f"Line {node.lineno}: Use of '.{node.attr}' is forbidden for security."
            )
        elif isinstance(node, ast.Call):
            func_name = _get_name(node.func)
            if func_name and func_name in FORBIDDEN_NAMES:
                result.add_error(
                    f"Line {node.lineno}: Call to '{func_name}' is forbidden for security."
                )


def _check_data_access(main_func: ast.AST, data_config: dict, result: ValidationResult) -> None:
    """Best-effort check that data[key] accesses match configured fields."""
    configured_fields = set()

    # Built-in fields
    fields = data_config.get("fields", {})
    for field_name, field_cfg in fields.items():
        if isinstance(field_cfg, dict) and field_cfg.get("enabled"):
            configured_fields.add(field_name)
        elif isinstance(field_cfg, int) and field_cfg > 0:
            configured_fields.add(field_name)

    # Custom data
    for custom in data_config.get("custom_data", []):
        name = custom.get("name") if isinstance(custom, dict) else None
        if name:
            configured_fields.add(name)
    for custom in data_config.get("custom_global_data", []):
        name = custom.get("name") if isinstance(custom, dict) else None
        if name:
            configured_fields.add(name)

    # Always available
    configured_fields.add("tickers")

    # Walk AST looking for data["key"] subscript patterns
    for node in ast.walk(main_func):
        if isinstance(node, ast.Subscript):
            # Check if it's data["something"]
            if isinstance(node.value, ast.Name) and node.value.id == "data":
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    key = node.slice.value
                    if key not in configured_fields:
                        result.add_error(
                            f"Line {node.lineno}: data[\"{key}\"] is not configured. "
                            f"Available: {', '.join(sorted(configured_fields))}"
                        )


def _get_name(node: ast.AST) -> str | None:
    """Extract a dotted name from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        parent = _get_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None
