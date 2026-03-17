# -*- coding: utf-8 -*-
"""Tests for roar_sdk.workflow — DAG-based workflow orchestration primitives."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from roar_sdk.types import MessageIntent
from roar_sdk.tracing import Tracer
from roar_sdk.workflow import (
    CyclicDependencyError,
    TaskStatus,
    Workflow,
    WorkflowEngine,
    WorkflowTask,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_workflow() -> Workflow:
    """A -> B, A -> C (fork)."""
    wf = Workflow("simple")
    a = wf.add_task("task-a", agent_did="did:roar:agent:alpha")
    wf.add_task("task-b", agent_did="did:roar:agent:beta", depends_on=[a.task_id])
    wf.add_task("task-c", agent_did="did:roar:agent:gamma", depends_on=[a.task_id])
    return wf


@pytest.fixture
def diamond_workflow() -> Workflow:
    """Diamond: A -> B, A -> C, B -> D, C -> D."""
    wf = Workflow("diamond")
    a = wf.add_task("task-a", agent_did="did:roar:agent:alpha")
    b = wf.add_task("task-b", agent_did="did:roar:agent:beta", depends_on=[a.task_id])
    c = wf.add_task("task-c", agent_did="did:roar:agent:gamma", depends_on=[a.task_id])
    wf.add_task("task-d", agent_did="did:roar:agent:delta", depends_on=[b.task_id, c.task_id])
    return wf


# ---------------------------------------------------------------------------
# Task creation and dependency tracking
# ---------------------------------------------------------------------------

class TestWorkflowTaskManagement:
    def test_add_task_creates_unique_ids(self) -> None:
        wf = Workflow("test")
        t1 = wf.add_task("a", agent_did="did:roar:agent:x")
        t2 = wf.add_task("b", agent_did="did:roar:agent:y")
        assert t1.task_id != t2.task_id
        assert t1.task_id.startswith("task_")
        assert t2.task_id.startswith("task_")

    def test_add_task_default_values(self) -> None:
        wf = Workflow("test")
        t = wf.add_task("my-task", agent_did="did:roar:agent:x", payload={"key": "val"})
        assert t.name == "my-task"
        assert t.agent_did == "did:roar:agent:x"
        assert t.payload == {"key": "val"}
        assert t.status == TaskStatus.PENDING
        assert t.result is None
        assert t.depends_on == []
        assert t.timeout_seconds == 300.0
        assert t.retry_count == 0
        assert t.max_retries == 0
        assert t.intent == MessageIntent.DELEGATE

    def test_add_task_with_dependencies(self, simple_workflow: Workflow) -> None:
        tasks = list(simple_workflow.tasks.values())
        root = [t for t in tasks if t.name == "task-a"][0]
        children = [t for t in tasks if t.name in ("task-b", "task-c")]
        for child in children:
            assert root.task_id in child.depends_on

    def test_add_task_invalid_dependency_raises(self) -> None:
        wf = Workflow("test")
        with pytest.raises(ValueError, match="not found"):
            wf.add_task("a", agent_did="did:roar:agent:x", depends_on=["nonexistent"])

    def test_add_task_custom_intent(self) -> None:
        wf = Workflow("test")
        t = wf.add_task("exec", agent_did="did:roar:agent:x", intent=MessageIntent.EXECUTE)
        assert t.intent == MessageIntent.EXECUTE


# ---------------------------------------------------------------------------
# get_ready_tasks
# ---------------------------------------------------------------------------

class TestGetReadyTasks:
    def test_root_tasks_ready_initially(self, simple_workflow: Workflow) -> None:
        ready = simple_workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].name == "task-a"

    def test_children_ready_after_parent_completes(self, simple_workflow: Workflow) -> None:
        root = [t for t in simple_workflow.tasks.values() if t.name == "task-a"][0]
        simple_workflow.complete_task(root.task_id, {"done": True})
        ready = simple_workflow.get_ready_tasks()
        names = {t.name for t in ready}
        assert names == {"task-b", "task-c"}

    def test_no_tasks_ready_when_deps_pending(self, diamond_workflow: Workflow) -> None:
        # Only task-a should be ready
        ready = diamond_workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].name == "task-a"

    def test_diamond_d_not_ready_until_both_b_c_complete(self, diamond_workflow: Workflow) -> None:
        tasks = diamond_workflow.tasks
        a = [t for t in tasks.values() if t.name == "task-a"][0]
        b = [t for t in tasks.values() if t.name == "task-b"][0]
        c = [t for t in tasks.values() if t.name == "task-c"][0]

        diamond_workflow.complete_task(a.task_id)
        diamond_workflow.complete_task(b.task_id)

        ready = diamond_workflow.get_ready_tasks()
        names = {t.name for t in ready}
        assert "task-d" not in names
        assert "task-c" in names

        diamond_workflow.complete_task(c.task_id)
        ready = diamond_workflow.get_ready_tasks()
        names = {t.name for t in ready}
        assert "task-d" in names


# ---------------------------------------------------------------------------
# Execution order (parallel batches)
# ---------------------------------------------------------------------------

class TestExecutionOrder:
    def test_linear_chain_produces_sequential_batches(self) -> None:
        wf = Workflow("linear")
        t1 = wf.add_task("step-1", agent_did="did:roar:agent:x")
        t2 = wf.add_task("step-2", agent_did="did:roar:agent:y", depends_on=[t1.task_id])
        t3 = wf.add_task("step-3", agent_did="did:roar:agent:z", depends_on=[t2.task_id])

        batches = wf.get_execution_order()
        assert len(batches) == 3
        assert batches[0][0].name == "step-1"
        assert batches[1][0].name == "step-2"
        assert batches[2][0].name == "step-3"

    def test_diamond_produces_correct_batches(self, diamond_workflow: Workflow) -> None:
        batches = diamond_workflow.get_execution_order()
        assert len(batches) == 3

        batch_names = [{t.name for t in batch} for batch in batches]
        assert batch_names[0] == {"task-a"}
        assert batch_names[1] == {"task-b", "task-c"}
        assert batch_names[2] == {"task-d"}

    def test_independent_tasks_in_single_batch(self) -> None:
        wf = Workflow("parallel")
        wf.add_task("a", agent_did="did:roar:agent:x")
        wf.add_task("b", agent_did="did:roar:agent:y")
        wf.add_task("c", agent_did="did:roar:agent:z")

        batches = wf.get_execution_order()
        assert len(batches) == 1
        assert len(batches[0]) == 3


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def test_complete_task(self) -> None:
        wf = Workflow("test")
        t = wf.add_task("a", agent_did="did:roar:agent:x")
        wf.complete_task(t.task_id, {"output": 42})
        assert t.status == TaskStatus.COMPLETED
        assert t.result == {"output": 42}

    def test_fail_task(self) -> None:
        wf = Workflow("test")
        t = wf.add_task("a", agent_did="did:roar:agent:x")
        wf.fail_task(t.task_id, "connection timeout")
        assert t.status == TaskStatus.FAILED
        assert t.error == "connection timeout"

    def test_cancel_task(self) -> None:
        wf = Workflow("test")
        t = wf.add_task("a", agent_did="did:roar:agent:x")
        wf.cancel_task(t.task_id)
        assert t.status == TaskStatus.CANCELLED

    def test_complete_unknown_task_raises(self) -> None:
        wf = Workflow("test")
        with pytest.raises(KeyError):
            wf.complete_task("nonexistent")

    def test_fail_unknown_task_raises(self) -> None:
        wf = Workflow("test")
        with pytest.raises(KeyError):
            wf.fail_task("nonexistent", "error")


# ---------------------------------------------------------------------------
# is_complete
# ---------------------------------------------------------------------------

class TestIsComplete:
    def test_empty_workflow_is_complete(self) -> None:
        wf = Workflow("empty")
        assert wf.is_complete() is True

    def test_not_complete_with_pending_tasks(self) -> None:
        wf = Workflow("test")
        wf.add_task("a", agent_did="did:roar:agent:x")
        assert wf.is_complete() is False

    def test_complete_when_all_done(self) -> None:
        wf = Workflow("test")
        t1 = wf.add_task("a", agent_did="did:roar:agent:x")
        t2 = wf.add_task("b", agent_did="did:roar:agent:y")
        wf.complete_task(t1.task_id)
        wf.fail_task(t2.task_id, "err")
        assert wf.is_complete() is True

    def test_complete_with_mix_of_terminal_states(self) -> None:
        wf = Workflow("test")
        t1 = wf.add_task("a", agent_did="did:roar:agent:x")
        t2 = wf.add_task("b", agent_did="did:roar:agent:y")
        t3 = wf.add_task("c", agent_did="did:roar:agent:z")
        wf.complete_task(t1.task_id)
        wf.fail_task(t2.task_id, "err")
        wf.cancel_task(t3.task_id)
        assert wf.is_complete() is True


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_round_trip(self, diamond_workflow: Workflow) -> None:
        # Complete one task to have mixed state
        tasks = list(diamond_workflow.tasks.values())
        a = [t for t in tasks if t.name == "task-a"][0]
        diamond_workflow.complete_task(a.task_id, {"fetched": True})

        data = diamond_workflow.to_dict()
        restored = Workflow.from_dict(data)

        assert restored.name == diamond_workflow.name
        assert len(restored.tasks) == len(diamond_workflow.tasks)

        for tid in diamond_workflow.tasks:
            orig = diamond_workflow.tasks[tid]
            rest = restored.tasks[tid]
            assert rest.task_id == orig.task_id
            assert rest.name == orig.name
            assert rest.agent_did == orig.agent_did
            assert rest.status == orig.status
            assert rest.result == orig.result
            assert rest.depends_on == orig.depends_on
            assert rest.intent == orig.intent

    def test_round_trip_preserves_payload(self) -> None:
        wf = Workflow("test")
        wf.add_task("a", agent_did="did:roar:agent:x", payload={"nested": {"key": [1, 2, 3]}})
        data = wf.to_dict()
        restored = Workflow.from_dict(data)
        t = list(restored.tasks.values())[0]
        assert t.payload == {"nested": {"key": [1, 2, 3]}}

    def test_to_dict_is_json_serializable(self, diamond_workflow: Workflow) -> None:
        import json
        data = diamond_workflow.to_dict()
        # Should not raise
        serialized = json.dumps(data)
        assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    def test_direct_cycle_raises(self) -> None:
        """Adding a task that depends on itself (via manipulation) is caught."""
        wf = Workflow("test")
        t1 = wf.add_task("a", agent_did="did:roar:agent:x")
        t2 = wf.add_task("b", agent_did="did:roar:agent:y", depends_on=[t1.task_id])
        # Manually inject a back-edge to create a cycle
        wf._tasks[t1.task_id].depends_on.append(t2.task_id)
        with pytest.raises(CyclicDependencyError):
            wf._check_cycles()

    def test_indirect_cycle_detected_on_add(self) -> None:
        """A -> B -> C -> A cycle."""
        wf = Workflow("test")
        a = wf.add_task("a", agent_did="did:roar:agent:x")
        b = wf.add_task("b", agent_did="did:roar:agent:y", depends_on=[a.task_id])
        c = wf.add_task("c", agent_did="did:roar:agent:z", depends_on=[b.task_id])
        # Now try to add a dependency from a -> c (making a cycle)
        # We need to manipulate and then trigger the check
        wf._tasks[a.task_id].depends_on.append(c.task_id)
        with pytest.raises(CyclicDependencyError):
            wf._check_cycles()

    def test_get_execution_order_rejects_cycles(self) -> None:
        wf = Workflow("test")
        a = wf.add_task("a", agent_did="did:roar:agent:x")
        b = wf.add_task("b", agent_did="did:roar:agent:y", depends_on=[a.task_id])
        # Inject cycle
        wf._tasks[a.task_id].depends_on.append(b.task_id)
        with pytest.raises(CyclicDependencyError):
            wf.get_execution_order()


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

class TestWorkflowEngine:
    @pytest.mark.asyncio
    async def test_executes_in_correct_order(self) -> None:
        """Tasks execute in dependency order."""
        execution_log: List[str] = []

        async def mock_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            execution_log.append(agent_did)
            return {"ok": True}

        wf = Workflow("ordered")
        t1 = wf.add_task("first", agent_did="agent-1")
        t2 = wf.add_task("second", agent_did="agent-2", depends_on=[t1.task_id])
        t3 = wf.add_task("third", agent_did="agent-3", depends_on=[t2.task_id])

        engine = WorkflowEngine(wf, send_fn=mock_send)
        results = await engine.run()

        assert execution_log == ["agent-1", "agent-2", "agent-3"]
        assert all(r["status"] == "completed" for r in results.values())

    @pytest.mark.asyncio
    async def test_parallel_execution(self) -> None:
        """Independent tasks can run concurrently."""
        execution_log: List[str] = []

        async def mock_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            execution_log.append(agent_did)
            return {"ok": True}

        wf = Workflow("parallel")
        t1 = wf.add_task("root", agent_did="agent-root")
        wf.add_task("branch-a", agent_did="agent-a", depends_on=[t1.task_id])
        wf.add_task("branch-b", agent_did="agent-b", depends_on=[t1.task_id])

        engine = WorkflowEngine(wf, send_fn=mock_send)
        await engine.run()

        # Root must execute first
        assert execution_log[0] == "agent-root"
        # Both branches must execute (order may vary since they're gathered)
        assert set(execution_log[1:]) == {"agent-a", "agent-b"}

    @pytest.mark.asyncio
    async def test_diamond_execution(self) -> None:
        """Diamond dependency: A -> B,C -> D."""
        execution_order: List[str] = []

        async def mock_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            execution_order.append(agent_did)
            return {"ok": True}

        wf = Workflow("diamond")
        a = wf.add_task("a", agent_did="agent-a")
        b = wf.add_task("b", agent_did="agent-b", depends_on=[a.task_id])
        c = wf.add_task("c", agent_did="agent-c", depends_on=[a.task_id])
        wf.add_task("d", agent_did="agent-d", depends_on=[b.task_id, c.task_id])

        engine = WorkflowEngine(wf, send_fn=mock_send)
        results = await engine.run()

        # a must be first, d must be last
        assert execution_order[0] == "agent-a"
        assert execution_order[-1] == "agent-d"
        assert set(execution_order[1:3]) == {"agent-b", "agent-c"}
        assert all(r["status"] == "completed" for r in results.values())

    @pytest.mark.asyncio
    async def test_retries_failed_tasks(self) -> None:
        """Tasks with max_retries > 0 are retried on failure."""
        call_count = 0

        async def flaky_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient failure")
            return {"recovered": True}

        wf = Workflow("retry")
        wf.add_task("flaky", agent_did="agent-flaky", max_retries=3)

        engine = WorkflowEngine(wf, send_fn=flaky_send)
        results = await engine.run()

        task_result = list(results.values())[0]
        assert task_result["status"] == "completed"
        assert task_result["result"] == {"recovered": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retries_exhausted_marks_failed(self) -> None:
        """Task fails permanently when retries are exhausted."""
        async def always_fail(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            raise RuntimeError("permanent failure")

        wf = Workflow("fail")
        wf.add_task("doomed", agent_did="agent-doom", max_retries=2)

        engine = WorkflowEngine(wf, send_fn=always_fail)
        results = await engine.run()

        task_result = list(results.values())[0]
        assert task_result["status"] == "failed"
        assert "permanent failure" in task_result["error"]

    @pytest.mark.asyncio
    async def test_downstream_cancelled_on_failure(self) -> None:
        """Tasks depending on a failed task get cancelled."""
        async def selective_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            if agent_did == "agent-fail":
                raise RuntimeError("boom")
            return {"ok": True}

        wf = Workflow("cancel-chain")
        t1 = wf.add_task("fail-task", agent_did="agent-fail")
        wf.add_task("dependent", agent_did="agent-ok", depends_on=[t1.task_id])

        engine = WorkflowEngine(wf, send_fn=selective_send)
        results = await engine.run()

        statuses = {list(wf.tasks.values())[i].name: r["status"] for i, r in enumerate(results.values())}
        assert statuses["fail-task"] == "failed"
        assert statuses["dependent"] == "cancelled"

    @pytest.mark.asyncio
    async def test_timeout_triggers_failure(self) -> None:
        """Task exceeding timeout is treated as failure."""
        async def slow_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            await asyncio.sleep(10)
            return {"ok": True}

        wf = Workflow("timeout")
        wf.add_task("slow", agent_did="agent-slow", timeout_seconds=0.05)

        engine = WorkflowEngine(wf, send_fn=slow_send)
        results = await engine.run()

        task_result = list(results.values())[0]
        assert task_result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_engine_with_tracer(self) -> None:
        """WorkflowEngine integrates with Tracer without errors."""
        async def mock_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            return {"ok": True}

        tracer = Tracer(service_name="test-workflow")
        wf = Workflow("traced", tracer=tracer)
        t1 = wf.add_task("a", agent_did="agent-a")
        wf.add_task("b", agent_did="agent-b", depends_on=[t1.task_id])

        engine = WorkflowEngine(wf, send_fn=mock_send)
        results = await engine.run()

        assert all(r["status"] == "completed" for r in results.values())
        # Tracer should have recorded spans (workflow + 2 tasks = 3)
        assert tracer.span_count >= 3

    @pytest.mark.asyncio
    async def test_engine_empty_workflow(self) -> None:
        """Running an empty workflow returns empty results."""
        async def mock_send(agent_did: str, intent: MessageIntent, payload: Dict[str, Any]) -> Dict[str, Any]:
            return {}

        wf = Workflow("empty")
        engine = WorkflowEngine(wf, send_fn=mock_send)
        results = await engine.run()
        assert results == {}


# ---------------------------------------------------------------------------
# WorkflowTask dataclass
# ---------------------------------------------------------------------------

class TestWorkflowTask:
    def test_task_to_dict(self) -> None:
        t = WorkflowTask(
            task_id="task_abc",
            name="test",
            agent_did="did:roar:agent:x",
            payload={"key": "value"},
            depends_on=["task_other"],
        )
        d = t.to_dict()
        assert d["task_id"] == "task_abc"
        assert d["name"] == "test"
        assert d["payload"] == {"key": "value"}
        assert d["depends_on"] == ["task_other"]
        assert d["status"] == "pending"

    def test_task_from_dict_round_trip(self) -> None:
        t = WorkflowTask(
            task_id="task_abc",
            name="test",
            agent_did="did:roar:agent:x",
            intent=MessageIntent.EXECUTE,
            payload={"a": 1},
            status=TaskStatus.COMPLETED,
            result={"b": 2},
            depends_on=["task_other"],
            timeout_seconds=60.0,
            retry_count=1,
            max_retries=3,
            error=None,
        )
        restored = WorkflowTask.from_dict(t.to_dict())
        assert restored.task_id == t.task_id
        assert restored.name == t.name
        assert restored.intent == t.intent
        assert restored.status == t.status
        assert restored.result == t.result
        assert restored.max_retries == t.max_retries
