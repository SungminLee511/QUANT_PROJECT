"""AST-based validation of user strategy code — enforces the BaseStrategy interface.

Code is NEVER executed during validation. Only parsed and inspected.
"""

import ast
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ALLOWED_IMPORTS = {
    # Python stdlib
    "math", "statistics", "collections", "itertools", "functools",
    "datetime", "decimal", "typing", "logging",
    # Data science
    "numpy", "pandas",
    # Project imports
    "shared.enums", "shared.schemas", "strategy.base",
}

FORBIDDEN_NAMES = {
    "os", "sys", "subprocess", "importlib", "eval", "exec",
    "open", "__import__", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "breakpoint",
}

REQUIRED_METHODS = {
    "on_tick": {
        "required_args": ["self", "tick"],
        "optional_args": ["extra_data"],
        "return_hint": "TradeSignal | None",
    },
    "on_bar": {
        "required_args": ["self", "bar"],
        "optional_args": ["extra_data"],
        "return_hint": "TradeSignal | None",
    },
}


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    class_name: str = ""

    def add_error(self, msg: str):
        self.valid = False
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def validate_strategy_code(source: str) -> ValidationResult:
    """Validate user strategy code via AST inspection. Returns ValidationResult."""
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

    # 4. Find strategy class
    classes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]

    strategy_classes = []
    for cls in classes:
        for base in cls.bases:
            base_name = _get_name(base)
            if base_name and "BaseStrategy" in base_name:
                strategy_classes.append(cls)
                break

    if len(strategy_classes) == 0:
        result.add_error(
            "Must define exactly one class that subclasses BaseStrategy. "
            "Example: class MyStrategy(BaseStrategy):"
        )
        return result

    if len(strategy_classes) > 1:
        result.add_error(
            f"Found {len(strategy_classes)} BaseStrategy subclasses — must have exactly one. "
            f"Classes found: {[c.name for c in strategy_classes]}"
        )
        return result

    cls_node = strategy_classes[0]
    result.class_name = cls_node.name

    # 5. Check required methods
    _check_required_methods(cls_node, result)

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


def _check_required_methods(cls_node: ast.ClassDef, result: ValidationResult) -> None:
    methods = {
        node.name: node
        for node in cls_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for method_name, spec in REQUIRED_METHODS.items():
        required_args = spec["required_args"]
        optional_args = spec.get("optional_args", [])

        if method_name not in methods:
            result.add_error(
                f"Missing required method: async def {method_name}"
                f"({', '.join(required_args)}) -> {spec['return_hint']}"
            )
            continue

        method = methods[method_name]

        # Must be async
        if not isinstance(method, ast.AsyncFunctionDef):
            result.add_error(
                f"'{method_name}' must be async: async def {method_name}(...)"
            )

        # Check parameter names — required args must match exactly,
        # extra args must be in the optional list
        args = [a.arg for a in method.args.args]
        if args[:len(required_args)] != required_args:
            result.add_error(
                f"'{method_name}' required parameters must start with "
                f"({', '.join(required_args)}), got ({', '.join(args)})"
            )
        extra_args = args[len(required_args):]
        for arg in extra_args:
            if arg not in optional_args:
                result.add_warning(
                    f"'{method_name}' has unexpected parameter '{arg}'. "
                    f"Known optional: {', '.join(optional_args) or 'none'}"
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
