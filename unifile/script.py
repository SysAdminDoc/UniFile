"""Restricted workflow scripts for trusted UniFile plugin hooks.

Workflow scripts are intentionally separate from legacy in-process plugins.
They run in a short-lived child process with a small object API and return
serializable commands to the host.  The static validator rejects imports,
dunder access, filesystem/network primitives, and unbounded ``while`` loops;
the process timeout is the final guard for scripts that still consume too much
CPU or memory.
"""
from __future__ import annotations

import ast
import multiprocessing
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

SCRIPT_HOOKS = ("on_scan_item", "on_apply")
MAX_SOURCE_BYTES = 256 * 1024
MAX_LOG_LINES = 200
MAX_COMMANDS = 500
DEFAULT_TIMEOUT_SECONDS = 3.0

_SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

_API_METHODS = {
    "classifier": {"classify", "category", "confidence", "method"},
    "tag_library": {"has_tag", "add_tag", "remove_tag"},
    "library": {"has_tag", "add_tag", "remove_tag"},
    "file_ops": {"move", "copy", "rename"},
}


class ScriptValidationError(ValueError):
    """Raised when a workflow script is outside the supported safe subset."""


class _ScriptValidator(ast.NodeVisitor):
    """Reject syntax that could reach host resources or evade the watchdog."""

    _blocked_nodes = (
        ast.AsyncFunctionDef,
        ast.AsyncFor,
        ast.AsyncWith,
        ast.ClassDef,
        ast.Delete,
        ast.Global,
        ast.Import,
        ast.ImportFrom,
        ast.Lambda,
        ast.Nonlocal,
        ast.Raise,
        ast.Try,
        ast.While,
        ast.With,
        ast.Yield,
        ast.YieldFrom,
    )

    def __init__(self, function_names: set[str]):
        self.function_names = function_names
        self.function_depth = 0

    @classmethod
    def validate(cls, tree: ast.Module) -> tuple[str, ...]:
        functions = tuple(
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        if not functions:
            raise ScriptValidationError(
                "Define at least one workflow function: on_scan_item or on_apply"
            )
        unknown_hooks = set(functions) - set(SCRIPT_HOOKS)
        if unknown_hooks:
            raise ScriptValidationError(
                f"Only supported workflow hooks are {', '.join(SCRIPT_HOOKS)}"
            )
        validator = cls(set(functions))
        validator.visit(tree)
        return functions

    def generic_visit(self, node):
        if isinstance(node, self._blocked_nodes):
            raise ScriptValidationError(
                f"{type(node).__name__} is not allowed in workflow scripts"
            )
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self.function_depth:
            raise ScriptValidationError("Nested function definitions are not allowed")
        if node.decorator_list:
            raise ScriptValidationError("Function decorators are not allowed")
        if node.returns:
            self.visit(node.returns)
        if any(arg.arg.startswith("_") for arg in node.args.args):
            raise ScriptValidationError("Private parameter names are not allowed")
        self.function_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.function_depth -= 1

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("_"):
            raise ScriptValidationError("Private and dunder attribute access is not allowed")
        if not isinstance(node.value, ast.Name) or node.value.id not in set(_API_METHODS) | {"item"}:
            raise ScriptValidationError(
                "Attribute access is limited to item, classifier, tag_library, library, and file_ops"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        function = node.func
        if isinstance(function, ast.Name):
            allowed = set(_SAFE_BUILTINS) | set(self.function_names) | {"log"}
            if function.id not in allowed:
                raise ScriptValidationError(f"Call to '{function.id}' is not allowed")
        elif isinstance(function, ast.Attribute):
            if not isinstance(function.value, ast.Name):
                raise ScriptValidationError("Chained method calls are not allowed")
            methods = _API_METHODS.get(function.value.id, set())
            if function.attr not in methods:
                raise ScriptValidationError(
                    f"'{function.value.id}.{function.attr}' is not an allowed workflow API call"
                )
        else:
            raise ScriptValidationError("Dynamic calls are not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id.startswith("_"):
            raise ScriptValidationError("Private and dunder names are not allowed")

    def visit_Import(self, node):  # pragma: no cover - handled by generic_visit
        raise ScriptValidationError("Imports are not allowed in workflow scripts")

    def visit_ImportFrom(self, node):  # pragma: no cover - handled by generic_visit
        raise ScriptValidationError("Imports are not allowed in workflow scripts")

    def visit_Assert(self, node: ast.Assert):
        self.visit(node.test)
        if node.msg:
            self.visit(node.msg)


def validate_script(source: str) -> tuple[str, ...]:
    """Validate source and return its declared workflow hook names."""
    if not isinstance(source, str):
        raise ScriptValidationError("Workflow source must be text")
    if not source.strip():
        raise ScriptValidationError("Workflow source is empty")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ScriptValidationError(f"Workflow source exceeds {MAX_SOURCE_BYTES} bytes")
    try:
        tree = ast.parse(source, filename="<unifile-workflow>")
    except SyntaxError as exc:
        raise ScriptValidationError(f"Syntax error on line {exc.lineno}: {exc.msg}") from exc
    return _ScriptValidator.validate(tree)


@dataclass
class ScriptResult:
    """Serializable result returned by a workflow execution."""

    success: bool
    timed_out: bool = False
    error: str = ""
    logs: list[str] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ScriptItem:
    """Small immutable-by-convention item view exposed to workflow scripts."""

    name: str = ""
    full_src: str = ""
    category: str = ""
    confidence: float = 0
    size: int = 0
    method: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Classification:
    category: str = ""
    confidence: float = 0
    method: str = ""


def item_to_payload(item: Any) -> dict[str, Any]:
    """Convert a FileItem or scan-result dict into a JSON-safe item view."""
    if isinstance(item, dict):
        source = item
    else:
        source = {
            "name": getattr(item, "name", ""),
            "full_src": getattr(item, "full_src", ""),
            "category": getattr(item, "category", ""),
            "confidence": getattr(item, "confidence", 0),
            "size": getattr(item, "size", 0),
            "method": getattr(item, "method", ""),
            "metadata": getattr(item, "metadata", {}),
        }
    return {
        "name": _safe_scalar(source.get("name", ""), str),
        "full_src": _safe_scalar(source.get("full_src", source.get("full_source_path", "")), str),
        "category": _safe_scalar(source.get("category", ""), str),
        "confidence": _safe_scalar(source.get("confidence", 0), float),
        "size": max(0, int(_safe_scalar(source.get("size", 0), float))),
        "method": _safe_scalar(source.get("method", ""), str),
        "metadata": _safe_json(source.get("metadata", {})),
    }


def _safe_scalar(value: Any, converter):
    try:
        return converter(value)
    except (TypeError, ValueError):
        return converter()


def _safe_json(value: Any, depth: int = 0):
    if depth > 4:
        return str(value)[:500]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key)[:120]: _safe_json(item, depth + 1)
            for key, item in list(value.items())[:200]
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item, depth + 1) for item in list(value)[:200]]
    return str(value)[:500]


def _item_view(payload: dict[str, Any]) -> ScriptItem:
    return ScriptItem(
        name=str(payload.get("name", "")),
        full_src=str(payload.get("full_src", "")),
        category=str(payload.get("category", "")),
        confidence=float(payload.get("confidence", 0) or 0),
        size=int(payload.get("size", 0) or 0),
        method=str(payload.get("method", "")),
        metadata=dict(payload.get("metadata", {})),
    )


def _item_path(item: ScriptItem | str) -> str:
    return item.full_src if isinstance(item, ScriptItem) else str(item)


def _validate_text(value: Any, label: str, maximum: int = 4096) -> str:
    text = str(value).strip()
    if not text or "\x00" in text or len(text) > maximum:
        raise ValueError(f"Invalid {label}")
    return text


class _ClassifierProxy:
    def __init__(self, values: dict[str, Any] | None):
        self._values = values or {}

    def _result(self, item: ScriptItem) -> _Classification:
        value = self._values.get(item.full_src, {})
        if not isinstance(value, dict):
            value = {}
        return _Classification(
            category=str(value.get("category", item.category)),
            confidence=float(value.get("confidence", item.confidence) or 0),
            method=str(value.get("method", item.method)),
        )

    def classify(self, item: ScriptItem) -> _Classification:
        return self._result(item)

    def category(self, item: ScriptItem) -> str:
        return self._result(item).category

    def confidence(self, item: ScriptItem) -> float:
        return self._result(item).confidence

    def method(self, item: ScriptItem) -> str:
        return self._result(item).method


class _TagLibraryProxy:
    def __init__(self, values: dict[str, Any] | None, commands: list[dict[str, Any]]):
        self._values = {
            str(path): {str(tag).strip().lower() for tag in tags}
            for path, tags in (values or {}).items()
            if isinstance(tags, (list, tuple, set))
        }
        self._commands = commands

    def has_tag(self, item: ScriptItem, tag: str) -> bool:
        return _validate_text(tag, "tag", 120).lower() in self._values.get(_item_path(item), set())

    def add_tag(self, item: ScriptItem, tag: str) -> None:
        path = _validate_text(_item_path(item), "item path")
        value = _validate_text(tag, "tag", 120)
        self._commands.append({"op": "tag_add", "path": path, "tag": value})
        self._values.setdefault(path, set()).add(value.lower())

    def remove_tag(self, item: ScriptItem, tag: str) -> None:
        path = _validate_text(_item_path(item), "item path")
        value = _validate_text(tag, "tag", 120)
        self._commands.append({"op": "tag_remove", "path": path, "tag": value})
        self._values.setdefault(path, set()).discard(value.lower())


class _FileOpsProxy:
    def __init__(self, commands: list[dict[str, Any]]):
        self._commands = commands

    def move(self, source: ScriptItem | str, destination: str) -> None:
        self._record("move", source, destination)

    def copy(self, source: ScriptItem | str, destination: str) -> None:
        self._record("copy", source, destination)

    def rename(self, source: ScriptItem | str, new_name: str) -> None:
        self._record("rename", source, new_name)

    def _record(self, operation: str, source: ScriptItem | str, destination: str) -> None:
        self._commands.append({
            "op": f"file_{operation}",
            "source": _validate_text(_item_path(source), "source path"),
            "destination": _validate_text(destination, "destination"),
        })


def _run_script_process(
    connection,
    source: str,
    hook: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    classifier_values: dict[str, Any] | None,
    tag_values: dict[str, Any] | None,
) -> None:
    """Process entry point. Keep this top-level for Windows spawn pickling."""
    try:
        hook_names = validate_script(source)
        if hook not in hook_names:
            raise ScriptValidationError(f"Workflow does not define {hook}")
        commands: list[dict[str, Any]] = []
        logs: list[str] = []

        def log(message: Any) -> None:
            if len(logs) < MAX_LOG_LINES:
                logs.append(str(message)[:2000])

        item_value = (
            [_item_view(item) for item in payload]
            if isinstance(payload, list)
            else _item_view(payload)
        )
        classifier = _ClassifierProxy(classifier_values)
        tag_library = _TagLibraryProxy(tag_values, commands)
        file_ops = _FileOpsProxy(commands)
        namespace = {
            "__builtins__": dict(_SAFE_BUILTINS),
            "classifier": classifier,
            "tag_library": tag_library,
            "library": tag_library,
            "file_ops": file_ops,
            "log": log,
        }
        exec(compile(source, "<unifile-workflow>", "exec"), namespace, namespace)
        function = namespace.get(hook)
        if not callable(function):
            raise ScriptValidationError(f"Workflow hook {hook} is not callable")
        if isinstance(item_value, list) and hook == "on_scan_item":
            for current_item in item_value:
                function(current_item, classifier, tag_library, file_ops, log)
        else:
            function(item_value, classifier, tag_library, file_ops, log)
        connection.send({"success": True, "logs": logs, "commands": commands[:MAX_COMMANDS]})
    except Exception as exc:
        connection.send({
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "logs": [],
            "commands": [],
        })
    finally:
        connection.close()


def execute_script(
    source: str,
    hook: str,
    item: Any,
    *,
    classifier_values: dict[str, Any] | None = None,
    tag_values: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ScriptResult:
    """Run one workflow hook in a bounded child process."""
    try:
        validate_script(source)
        if hook not in SCRIPT_HOOKS:
            raise ScriptValidationError(f"Unsupported workflow hook: {hook}")
    except ScriptValidationError as exc:
        return ScriptResult(False, error=str(exc))

    payload = item_to_payload(item) if not isinstance(item, list) else [item_to_payload(value) for value in item]
    bounded_timeout = min(60.0, max(0.1, float(timeout)))
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_script_process,
        args=(child, source, hook, payload, _safe_json(classifier_values or {}), _safe_json(tag_values or {})),
    )
    process.daemon = True
    try:
        process.start()
        child.close()
        if not parent.poll(bounded_timeout):
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(1)
            return ScriptResult(False, timed_out=True, error=f"Script timed out after {bounded_timeout:.1f}s")
        response = parent.recv()
        process.join(2)
        return ScriptResult(
            bool(response.get("success")),
            error=str(response.get("error", "")),
            logs=list(response.get("logs", [])),
            commands=list(response.get("commands", [])),
        )
    except (EOFError, OSError, RuntimeError) as exc:
        if process.is_alive():
            process.terminate()
        process.join(2)
        return ScriptResult(False, error=f"Script process failed: {exc}")
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(1)


def workflow_template() -> str:
    """Return a safe starter script for the embedded editor."""
    return '''"""Tag large photos after classification.
Workflow-Hook: on_scan_item
"""

def on_scan_item(item, classifier, tag_library, file_ops, log):
    if item.category == "Photo" and item.size > 10_000_000:
        tag_library.add_tag(item, "hires")
        log(f"Tagged {item.name} as hires")
'''


class ScriptExecutionWorker(QThread):
    """QThread wrapper used by the plugin editor and host integrations."""

    result_ready = pyqtSignal(object)
    log = pyqtSignal(str)

    def __init__(self, source: str, hook: str, item: Any, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 classifier_values: dict[str, Any] | None = None,
                 tag_values: dict[str, Any] | None = None):
        super().__init__()
        self.source = source
        self.hook = hook
        self.item = item
        self.timeout = timeout
        self.classifier_values = classifier_values
        self.tag_values = tag_values

    def run(self):
        result = execute_script(
            self.source,
            self.hook,
            self.item,
            timeout=self.timeout,
            classifier_values=self.classifier_values,
            tag_values=self.tag_values,
        )
        for message in result.logs:
            self.log.emit(message)
        self.result_ready.emit(result)


class WorkflowBatchWorker(QThread):
    """Run all trusted workflow jobs for a scan batch off the GUI thread."""

    result_ready = pyqtSignal(object)
    log = pyqtSignal(str)

    def __init__(self, jobs: list[dict[str, Any]], hook: str, items: list[Any], *,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 classifier_values: dict[str, Any] | None = None,
                 tag_values: dict[str, Any] | None = None):
        super().__init__()
        self.jobs = jobs
        self.hook = hook
        self.items = items
        self.timeout = timeout
        self.classifier_values = classifier_values
        self.tag_values = tag_values

    def run(self):
        results = []
        for job in self.jobs:
            result = execute_script(
                job["source"],
                self.hook,
                self.items,
                timeout=self.timeout,
                classifier_values=self.classifier_values,
                tag_values=self.tag_values,
            )
            for message in result.logs:
                self.log.emit(f"[{job['name']}] {message}")
            results.append({"job": job, "result": result})
        self.result_ready.emit(results)
