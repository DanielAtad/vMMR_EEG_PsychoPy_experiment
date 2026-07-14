import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SCRIPT = ROOT / "run_vMMR_experiment_v0.py"


def test_parallel_backend_requires_manual_clear():
    tree = ast.parse(MAIN_SCRIPT.read_text(encoding="utf-8"))
    eeg_trigger = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EEGTrigger"
    )
    assignments = {
        target.id: node.value.value
        for node in eeg_trigger.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert assignments["requires_manual_clear"] is True


def test_frame_two_clear_is_centralized_and_backend_conditional():
    source = MAIN_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_schedule_manual_clear_if_required"
    )
    helper_source = ast.get_source_segment(source, helper)

    assert "frame_n == 1" in helper_source
    assert 'getattr(trigger, "requires_manual_clear", False)' in helper_source
    assert "win.callOnFlip(trigger.clear)" in helper_source
    assert source.count("win.callOnFlip(trigger.clear)") == 1

    helper_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_schedule_manual_clear_if_required"
    ]
    assert len(helper_calls) == 3
