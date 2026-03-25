"""AST-based validation of custom data functions — more permissive than strategy validator.

Allows network access (requests, urllib) but blocks dangerous operations.
Code is NEVER executed during validation.
"""

import ast
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Custom data functions can access the network
ALLOWED_IMPORTS = {
    # Python stdlib
    "math", "statistics", "collections", "itertools", "functools",
    "datetime", "decimal", "typing", "logging", "json", "re", "time",
    # Network (allowed for custom data)
    "requests", "urllib",
    # Data science
    "numpy", "pandas",
}

FORBIDDEN_NAMES = {
    "subprocess", "importlib", "eval", "exec",
    "__import__", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "breakpoint",
    "os", "sys", "shutil", "pathlib",
}


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.valid = False
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def validate_custom_data_function(
    source: str,
    func_type: str = "per_stock",
) -> ValidationResult:
    """Validate a custom data function.

    Args:
        source: Python source code containing a fetch() function.
        func_type: "per_stock" or "global".
            per_stock: fetch(tickers: list[str]) -> np.ndarray  (shape [N])
            global: fetch() -> float
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

    # 3. Check forbidden names
    _check_forbidden_names(tree, result)

    # 4. Find fetch() function
    fetch_funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "fetch"
    ]

    if len(fetch_funcs) == 0:
        result.add_error(
            "Must define a function named 'fetch'. "
            f"{'Example: def fetch(tickers: list[str]) -> np.ndarray:' if func_type == 'per_stock' else 'Example: def fetch() -> float:'}"
        )
        return result

    if len(fetch_funcs) > 1:
        result.add_error("Found multiple 'fetch' functions — must have exactly one.")
        return result

    fetch_func = fetch_funcs[0]
    args = [a.arg for a in fetch_func.args.args]

    # 5. Check parameter signature
    if func_type == "per_stock":
        if args != ["tickers"]:
            result.add_error(
                f"Per-stock fetch must take one parameter 'tickers', got ({', '.join(args)})"
            )
    elif func_type == "global":
        if args:
            result.add_error(
                f"Global fetch must take no parameters, got ({', '.join(args)})"
            )

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
