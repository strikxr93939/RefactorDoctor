import ast
from dataclasses import dataclass, field


def _name(identifier: str) -> ast.Name:
    return ast.Name(id=identifier, ctx=ast.Load())


def _google_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [
        arg.arg
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if arg.arg not in {"self", "cls"}
    ]
    lines = [f"{node.name.replace('_', ' ').capitalize()}."]
    if args:
        lines.extend(["", "Args:"])
        lines.extend(f"    {name}: Description of {name}." for name in args)
    if node.name != "__init__":
        lines.extend(["", "Returns:", "    Result of the operation."])
    return "\n".join(lines)


def _numpy_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [
        arg.arg
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if arg.arg not in {"self", "cls"}
    ]
    lines = [f"{node.name.replace('_', ' ').capitalize()}."]
    if args:
        lines.extend(["", "Parameters", "----------"])
        lines.extend(f"{name} : Any\n    Description of {name}." for name in args)
    if node.name != "__init__":
        lines.extend(["", "Returns", "-------", "Any", "    Result of the operation."])
    return "\n".join(lines)


@dataclass
class TransformState:
    changes: list[str] = field(default_factory=list)
    needs_any: bool = False
    needs_logging: bool = False
    needs_path: bool = False


class LegacyTransformer(ast.NodeTransformer):
    """Conservative AST modernization with interface-preserving replacements."""

    def __init__(self, docstring_style: str = "google") -> None:
        self.state = TransformState()
        self.docstring_style = docstring_style

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.generic_visit(node)
        return self._modernize_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.generic_visit(node)
        return self._modernize_function(node)

    def _modernize_function(self, node):
        annotation_added = False
        all_args = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        if node.args.vararg:
            all_args.append(node.args.vararg)
        if node.args.kwarg:
            all_args.append(node.args.kwarg)
        for argument in all_args:
            if argument.arg not in {"self", "cls"} and argument.annotation is None:
                argument.annotation = _name("Any")
                annotation_added = True
        if node.returns is None:
            node.returns = (
                ast.Constant(value=None) if node.name == "__init__" else _name("Any")
            )
            annotation_added = True
        if annotation_added:
            self.state.needs_any = True
            self.state.changes.append(f"Добавлены type hints: {node.name}")
        if not ast.get_docstring(node, clean=False):
            builder = (
                _numpy_docstring
                if self.docstring_style == "numpy"
                else _google_docstring
            )
            node.body.insert(0, ast.Expr(value=ast.Constant(value=builder(node))))
            self.state.changes.append(f"Добавлен docstring: {node.name}")
        return node

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            self.state.needs_logging = True
            self.state.changes.append("print заменён на logger.info")
            values = ast.List(elts=node.args, ctx=ast.Load())
            rendered = ast.Call(
                func=ast.Attribute(
                    value=ast.Constant(value=" "), attr="join", ctx=ast.Load()
                ),
                args=[
                    ast.Call(
                        func=_name("map"),
                        args=[_name("str"), values],
                        keywords=[],
                    )
                ],
                keywords=[],
            )
            return ast.Call(
                func=ast.Attribute(value=_name("logger"), attr="info", ctx=ast.Load()),
                args=[ast.Constant(value="%s"), rendered],
                keywords=[],
            )

        path_call = self._os_path_call(node)
        return path_call or node

    def _os_path_call(self, node: ast.Call) -> ast.AST | None:
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
            and node.func.value.attr == "path"
        ):
            return None
        operation = node.func.attr
        if not node.args:
            return None
        self.state.needs_path = True
        path = ast.Call(func=_name("Path"), args=[node.args[0]], keywords=[])
        replacement: ast.AST | None = None
        if operation == "join":
            joined = ast.Call(
                func=ast.Attribute(value=path, attr="joinpath", ctx=ast.Load()),
                args=node.args[1:],
                keywords=[],
            )
            replacement = ast.Call(func=_name("str"), args=[joined], keywords=[])
        elif operation in {"exists", "isfile", "isdir"}:
            method = {"exists": "exists", "isfile": "is_file", "isdir": "is_dir"}[
                operation
            ]
            replacement = ast.Call(
                func=ast.Attribute(value=path, attr=method, ctx=ast.Load()),
                args=[],
                keywords=[],
            )
        elif operation == "basename":
            replacement = ast.Attribute(value=path, attr="name", ctx=ast.Load())
        elif operation == "dirname":
            replacement = ast.Call(
                func=_name("str"),
                args=[ast.Attribute(value=path, attr="parent", ctx=ast.Load())],
                keywords=[],
            )
        elif operation == "abspath":
            resolved = ast.Call(
                func=ast.Attribute(value=path, attr="resolve", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            replacement = ast.Call(func=_name("str"), args=[resolved], keywords=[])
        if replacement is not None:
            self.state.changes.append(f"os.path.{operation} заменён на pathlib")
        else:
            self.state.needs_path = False
        return replacement


def _has_import(module: ast.Module, imported: str, name: str | None = None) -> bool:
    for statement in module.body:
        if isinstance(statement, ast.Import):
            if any(alias.name == imported for alias in statement.names):
                return True
        elif (
            isinstance(statement, ast.ImportFrom)
            and statement.module == imported
            and (name is None or any(alias.name == name for alias in statement.names))
        ):
            return True
    return False


def _remove_unused_os_import(module: ast.Module) -> None:
    os_is_used = any(
        isinstance(node, ast.Name)
        and node.id == "os"
        and isinstance(node.ctx, ast.Load)
        for node in ast.walk(module)
    )
    if os_is_used:
        return
    cleaned: list[ast.stmt] = []
    for statement in module.body:
        if isinstance(statement, ast.Import):
            statement.names = [alias for alias in statement.names if alias.name != "os"]
            if not statement.names:
                continue
        cleaned.append(statement)
    module.body = cleaned


def transform_legacy_code(
    code: str, docstring_style: str = "google"
) -> tuple[str, list[str]]:
    tree = ast.parse(code)
    transformer = LegacyTransformer(docstring_style)
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)

    if not ast.get_docstring(tree, clean=False):
        tree.body.insert(
            0,
            ast.Expr(value=ast.Constant(value="Modernized Python module.")),
        )
        transformer.state.changes.append("Добавлен docstring модуля")
    _remove_unused_os_import(tree)

    insert_at = (
        1
        if tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
        else 0
    )
    imports: list[ast.stmt] = []
    if transformer.state.needs_any and not _has_import(tree, "typing", "Any"):
        imports.append(
            ast.ImportFrom(module="typing", names=[ast.alias(name="Any")], level=0)
        )
    if transformer.state.needs_path and not _has_import(tree, "pathlib", "Path"):
        imports.append(
            ast.ImportFrom(module="pathlib", names=[ast.alias(name="Path")], level=0)
        )
    if transformer.state.needs_logging:
        if not _has_import(tree, "logging"):
            imports.append(ast.Import(names=[ast.alias(name="logging")]))
        logger_assignment = ast.Assign(
            targets=[ast.Name(id="logger", ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(
                    value=_name("logging"), attr="getLogger", ctx=ast.Load()
                ),
                args=[_name("__name__")],
                keywords=[],
            ),
        )
        imports.append(logger_assignment)
    tree.body[insert_at:insert_at] = imports
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", transformer.state.changes
