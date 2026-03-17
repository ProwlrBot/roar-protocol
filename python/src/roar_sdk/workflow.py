# -*- coding: utf-8 -*-
"""ROAR Protocol — Workflow orchestration primitives for multi-agent coordination.

Provides DAG-based task dependency resolution, parallel execution of independent
tasks, retry logic, and serializable state for checkpointing.

Usage::

    from roar_sdk.workflow import Workflow, WorkflowEngine, TaskStatus
    from roar_sdk.tracing import Tracer

    tracer = Tracer()
    wf = Workflow("data-pipeline", tracer=tracer)

    t1 = wf.add_task("fetch-data", agent_did="did:roar:agent:fetcher-abc", payload={"url": "..."})
    t2 = wf.add_task("parse-data", agent_did="did:roar:agent:parser-def", payload={}, depends_on=[t1.task_id])
    t3 = wf.add_task("validate", agent_did="did:roar:agent:validator-ghi", payload={}, depends_on=[t1.task_id])
    t4 = wf.add_task("store", agent_did="did:roar:agent:store-jkl", payload={}, depends_on=[t2.task_id, t3.task_id])

    async def send(agent_did, intent, payload):
        # your transport logic
        return {"status": "ok"}

    engine = WorkflowEngine(wf, send_fn=send)
    results = await engine.run()
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ._compat import StrEnum
from .types import MessageIntent


class TaskStatus(StrEnum):
    """Lifecycle state of a workflow task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowTask:
    """A single unit of work within a workflow DAG."""

    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    name: str = ""
    agent_did: str = ""
    intent: MessageIntent = MessageIntent.DELEGATE
    payload: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    depends_on: List[str] = field(default_factory=list)
    timeout_seconds: float = 300.0
    retry_count: int = 0
    max_retries: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "agent_did": self.agent_did,
            "intent": str(self.intent),
            "payload": self.payload,
            "status": str(self.status),
            "result": self.result,
            "depends_on": list(self.depends_on),
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkflowTask:
        return cls(
            task_id=data["task_id"],
            name=data.get("name", ""),
            agent_did=data.get("agent_did", ""),
            intent=MessageIntent(data.get("intent", "delegate")),
            payload=data.get("payload", {}),
            status=TaskStatus(data.get("status", "pending")),
            result=data.get("result"),
            depends_on=data.get("depends_on", []),
            timeout_seconds=data.get("timeout_seconds", 300.0),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 0),
            error=data.get("error"),
        )


class CyclicDependencyError(ValueError):
    """Raised when a workflow DAG contains a cycle."""


class Workflow:
    """A directed acyclic graph of tasks for multi-agent coordination.

    Tasks declare dependencies on other tasks by task_id. The workflow
    tracks state transitions and provides dependency-aware scheduling.
    """

    def __init__(self, name: str, tracer: Any = None) -> None:
        self.name = name
        self.tracer = tracer
        self._tasks: Dict[str, WorkflowTask] = {}

    @property
    def tasks(self) -> Dict[str, WorkflowTask]:
        return dict(self._tasks)

    def add_task(
        self,
        name: str,
        agent_did: str,
        payload: Optional[Dict[str, Any]] = None,
        depends_on: Optional[List[str]] = None,
        intent: MessageIntent = MessageIntent.DELEGATE,
        timeout_seconds: float = 300.0,
        max_retries: int = 0,
    ) -> WorkflowTask:
        """Add a task to the workflow. Returns the created WorkflowTask."""
        dep_list = depends_on or []
        # Validate that dependencies reference existing tasks
        for dep_id in dep_list:
            if dep_id not in self._tasks:
                raise ValueError(f"Dependency '{dep_id}' not found in workflow")

        task = WorkflowTask(
            name=name,
            agent_did=agent_did,
            intent=intent,
            payload=payload or {},
            depends_on=dep_list,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self._tasks[task.task_id] = task

        # Validate no cycles were introduced
        self._check_cycles()

        return task

    def _check_cycles(self) -> None:
        """Detect cycles in the dependency graph using Kahn's algorithm."""
        # Build adjacency and in-degree maps
        in_degree: Dict[str, int] = {tid: 0 for tid in self._tasks}
        adj: Dict[str, List[str]] = {tid: [] for tid in self._tasks}
        for tid, task in self._tasks.items():
            for dep in task.depends_on:
                if dep in adj:
                    adj[dep].append(tid)
                    in_degree[tid] += 1

        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self._tasks):
            raise CyclicDependencyError(
                "Workflow contains a cyclic dependency"
            )

    def get_ready_tasks(self) -> List[WorkflowTask]:
        """Return tasks whose dependencies are all COMPLETED and that are PENDING."""
        ready = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_met = all(
                self._tasks[dep].status == TaskStatus.COMPLETED
                for dep in task.depends_on
                if dep in self._tasks
            )
            if deps_met:
                ready.append(task)
        return ready

    def complete_task(self, task_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark a task as completed with an optional result dict."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.error = None

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed with an error message."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")
        task.status = TaskStatus.FAILED
        task.error = error

    def cancel_task(self, task_id: str) -> None:
        """Mark a task as cancelled."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")
        task.status = TaskStatus.CANCELLED

    def is_complete(self) -> bool:
        """True when every task is in a terminal state (COMPLETED, FAILED, or CANCELLED)."""
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        return all(t.status in terminal for t in self._tasks.values())

    def get_execution_order(self) -> List[List[WorkflowTask]]:
        """Compute parallel execution batches via topological sort.

        Returns a list of batches. Each batch is a list of tasks that can
        run concurrently. Batches must execute sequentially.
        """
        self._check_cycles()

        # Build in-degree map considering only PENDING/RUNNING tasks
        remaining = {
            tid for tid, t in self._tasks.items()
            if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
        }
        in_degree: Dict[str, int] = {}
        adj: Dict[str, List[str]] = {}
        for tid in remaining:
            in_degree[tid] = 0
            adj[tid] = []
        for tid in remaining:
            task = self._tasks[tid]
            for dep in task.depends_on:
                if dep in remaining:
                    adj[dep].append(tid)
                    in_degree[tid] += 1

        batches: List[List[WorkflowTask]] = []
        current = [tid for tid, deg in in_degree.items() if deg == 0]
        while current:
            batch = [self._tasks[tid] for tid in current]
            batches.append(batch)
            next_level: List[str] = []
            for tid in current:
                for neighbor in adj.get(tid, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_level.append(neighbor)
            current = next_level

        return batches

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the workflow to a plain dict for checkpointing."""
        return {
            "name": self.name,
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], tracer: Any = None) -> Workflow:
        """Deserialize a workflow from a dict."""
        wf = cls(name=data["name"], tracer=tracer)
        for tid, tdata in data["tasks"].items():
            task = WorkflowTask.from_dict(tdata)
            wf._tasks[task.task_id] = task
        return wf


# Type alias for the send function
SendFn = Callable[[str, MessageIntent, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]


class WorkflowEngine:
    """Executes a Workflow by dispatching tasks to agents via a send function.

    The engine respects dependency ordering, runs independent tasks in
    parallel using asyncio.gather, and supports retry on failure.
    """

    def __init__(self, workflow: Workflow, send_fn: SendFn) -> None:
        self.workflow = workflow
        self.send_fn = send_fn

    async def _execute_task(self, task: WorkflowTask) -> None:
        """Execute a single task, handling timeout and retries."""
        tracer = self.workflow.tracer
        span_ctx = None
        if tracer is not None:
            span_ctx = tracer.span(f"workflow-task:{task.name}")
            span_ctx.__enter__()
            span_ctx.set_attribute("task_id", task.task_id)
            span_ctx.set_attribute("agent_did", task.agent_did)

        task.status = TaskStatus.RUNNING
        last_error: Optional[str] = None

        attempts = 1 + task.max_retries
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    self.send_fn(task.agent_did, task.intent, task.payload),
                    timeout=task.timeout_seconds,
                )
                self.workflow.complete_task(task.task_id, result)
                if span_ctx is not None:
                    span_ctx.set_attribute("status", "completed")
                    span_ctx.set_attribute("attempts", attempt + 1)
                    span_ctx.__exit__(None, None, None)
                return
            except Exception as exc:
                last_error = str(exc)
                task.retry_count = attempt + 1
                if attempt < task.max_retries:
                    # Reset to RUNNING for next attempt
                    task.status = TaskStatus.RUNNING
                    continue

        # All attempts exhausted
        self.workflow.fail_task(task.task_id, last_error or "unknown error")
        if span_ctx is not None:
            span_ctx.set_attribute("status", "failed")
            span_ctx.set_attribute("error", last_error)
            span_ctx.set_attribute("attempts", attempts)
            span_ctx.__exit__(None, None, None)

    async def run(self) -> Dict[str, Any]:
        """Execute the workflow to completion.

        Returns a dict mapping task_id to its result (or error info).
        """
        # Validate DAG before execution
        self.workflow._check_cycles()

        tracer = self.workflow.tracer
        wf_span = None
        if tracer is not None:
            wf_span = tracer.span(f"workflow:{self.workflow.name}")
            wf_span.__enter__()

        while not self.workflow.is_complete():
            ready = self.workflow.get_ready_tasks()
            if not ready:
                # No tasks ready but workflow not complete — blocked by failed deps
                # Cancel all remaining pending tasks
                for task in self.workflow._tasks.values():
                    if task.status == TaskStatus.PENDING:
                        self.workflow.cancel_task(task.task_id)
                break

            await asyncio.gather(*(self._execute_task(t) for t in ready))

        if wf_span is not None:
            wf_span.set_attribute("workflow_name", self.workflow.name)
            wf_span.set_attribute("total_tasks", len(self.workflow._tasks))
            wf_span.__exit__(None, None, None)

        # Build results summary
        results: Dict[str, Any] = {}
        for tid, task in self.workflow._tasks.items():
            if task.status == TaskStatus.COMPLETED:
                results[tid] = {"status": "completed", "result": task.result}
            elif task.status == TaskStatus.FAILED:
                results[tid] = {"status": "failed", "error": task.error}
            elif task.status == TaskStatus.CANCELLED:
                results[tid] = {"status": "cancelled"}
            else:
                results[tid] = {"status": str(task.status)}

        return results
