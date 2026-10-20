"""Generate a balanced, restartable core-CS question bank from curated concepts.

The catalog is intentionally local and versionable: generation does not require an
LLM, network access, or a framework-specific knowledge source.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from psycopg2.extras import execute_values

from database import transaction

ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT / "bankresume_schema.sql"
REPORT = ROOT / "question_bank_report.json"

CORE_TARGETS = {
    "Object-Oriented Programming (OOP)": 250,
    "Data Structures": 250,
    "Algorithms": 250,
    "Database Management Systems (DBMS)": 250,
    "SQL": 250,
    "Computer Networks": 250,
    "Operating Systems": 250,
    "Software Engineering": 250,
    "Software Development Life Cycle (SDLC)": 250,
    "System Design Fundamentals": 250,
    "Computer Architecture": 250,
    "Programming Fundamentals": 250,
    "Git / Version Control": 250,
    "Software Testing Fundamentals": 250,
}
LANGUAGE_TARGETS = {
    "Java": 121, "Python": 121, "JavaScript": 121, "C++": 121, "C": 121,
    "C#": 121, "Go / Golang": 121, "TypeScript": 121, "Kotlin": 121,
    "PHP": 121, "Ruby": 121, "Rust": 121, "Dart": 121, "Scala": 121,
}
TARGETS = {**CORE_TARGETS, **LANGUAGE_TARGETS}

CORE_CONCEPTS = {
    "Object-Oriented Programming (OOP)": ["encapsulation", "inheritance", "polymorphism", "abstraction", "composition"],
    "Data Structures": ["arrays", "linked lists", "stacks", "queues", "hash tables", "trees", "graphs"],
    "Algorithms": ["binary search", "sorting", "recursion", "dynamic programming", "greedy algorithms", "graph traversal", "complexity analysis"],
    "Database Management Systems (DBMS)": ["normalization", "transactions", "ACID properties", "indexes", "query optimizer", "locking", "write-ahead logging"],
    "SQL": ["SELECT and filtering", "JOINs", "GROUP BY and HAVING", "subqueries", "common table expressions", "window functions", "constraints", "transactions"],
    "Computer Networks": ["OSI model", "TCP", "UDP", "DNS", "HTTP", "subnetting", "routing", "TLS"],
    "Operating Systems": ["processes", "threads", "virtual memory", "deadlock", "scheduling", "file systems", "system calls"],
    "Software Engineering": ["cohesion and coupling", "modularity", "technical debt", "code review", "refactoring", "requirements", "design patterns"],
    "Software Development Life Cycle (SDLC)": ["requirements analysis", "architecture phase", "implementation", "verification", "release", "maintenance", "risk management"],
    "System Design Fundamentals": ["load balancing", "caching", "partitioning", "replication", "message queues", "rate limiting", "idempotency"],
    "Computer Architecture": ["CPU pipeline", "cache locality", "instruction set", "branch prediction", "virtual addressing", "interrupts", "DMA"],
    "Programming Fundamentals": ["variables and scope", "data types", "functions", "recursion", "exceptions", "memory management", "concurrency"],
    "Git / Version Control": ["commits", "branches", "merge", "rebase", "conflicts", "revert", "bisect"],
    "Software Testing Fundamentals": ["unit testing", "integration testing", "system testing", "regression testing", "test doubles", "property-based testing", "boundary analysis"],
}
LANGUAGE_CONCEPTS = {
    language: ["variables and types", "functions", "classes and objects", "collections", "exceptions", "memory model", "concurrency"]
    for language in LANGUAGE_TARGETS
}

CONTEXTS = [
    "a production service", "a command-line utility", "a data-processing pipeline",
    "a multi-user application", "a resource-constrained device", "a batch job",
    "a library used by several teams", "a concurrent server", "a system under test",
]

DEFINITIONS = {
    "encapsulation": "Encapsulation keeps an object's state behind a controlled interface so callers depend on operations rather than representation.",
    "inheritance": "Inheritance derives a specialized type from a base type and reuses or extends its behavior.",
    "polymorphism": "Polymorphism lets one interface select different implementations according to the object's actual type.",
    "abstraction": "Abstraction exposes essential behavior while hiding implementation details that users do not need to manage.",
    "composition": "Composition builds a type from collaborating objects and usually favors explicit delegation over a rigid hierarchy.",
    "arrays": "An array stores elements in indexed positions, normally in contiguous storage, which gives constant-time indexed access.",
    "linked lists": "A linked list stores nodes connected by references, so insertion can be cheap when the relevant node is already known.",
    "stacks": "A stack is a last-in-first-out structure with push and pop operations at one end.",
    "queues": "A queue is a first-in-first-out structure that separates adding work from removing the oldest work.",
    "hash tables": "A hash table maps keys to buckets using a hash function and resolves collisions with a defined strategy.",
    "trees": "A tree is a hierarchical, acyclic structure whose nodes have parent-child relationships.",
    "graphs": "A graph represents entities as vertices and relationships as edges, which may be directed or weighted.",
    "binary search": "Binary search repeatedly halves a sorted search range to locate a value in logarithmic time.",
    "sorting": "Sorting arranges values according to an ordering relation so later searches or merges can be performed predictably.",
    "recursion": "Recursion solves a problem by reducing it to smaller instances and stopping at a base case.",
    "dynamic programming": "Dynamic programming stores results of overlapping subproblems so each needed state is solved once.",
    "greedy algorithms": "A greedy algorithm makes the best local choice available at each step and relies on a proof that this leads to a global optimum.",
    "graph traversal": "Graph traversal systematically visits reachable vertices, commonly with breadth-first or depth-first search.",
    "complexity analysis": "Complexity analysis estimates how time or space grows with input size rather than measuring one machine run.",
    "normalization": "Normalization organizes relational data to reduce update anomalies while preserving well-defined dependencies.",
    "transactions": "A transaction groups database operations into one logical unit with commit or rollback semantics.",
    "ACID properties": "ACID describes atomicity, consistency, isolation, and durability as guarantees expected from reliable transactions.",
    "indexes": "An index is an auxiliary data structure that accelerates selected lookups at the cost of storage and write work.",
    "query optimizer": "A query optimizer compares execution strategies and selects one based on estimated cost and available statistics.",
    "locking": "Locking coordinates concurrent access by restricting incompatible operations on shared data.",
    "write-ahead logging": "Write-ahead logging records recovery information before changing durable data pages.",
    "OSI model": "The OSI model separates networking responsibilities into seven conceptual layers to make protocols and failures easier to reason about.",
    "TCP": "TCP provides an ordered, reliable byte stream using sequence numbers, acknowledgments, retransmission, and congestion control.",
    "UDP": "UDP provides connectionless datagrams with minimal transport overhead and no built-in delivery guarantee.",
    "DNS": "DNS maps domain names to records such as IP addresses through a hierarchical and cached naming system.",
    "HTTP": "HTTP is a request-response application protocol whose methods and status codes describe resource operations and outcomes.",
    "subnetting": "Subnetting divides an IP address space into smaller prefixes to control routing scope and address allocation.",
    "routing": "Routing selects a path for packets across interconnected networks using destination information and routing policy.",
    "TLS": "TLS authenticates a peer and protects application traffic with negotiated cryptographic keys and integrity checks.",
    "processes": "A process is an executing program with an isolated address space and operating-system-managed resources.",
    "threads": "A thread is an execution path within a process that shares the process's memory and resources.",
    "virtual memory": "Virtual memory maps process addresses to physical storage and can provide isolation plus a larger apparent address space.",
    "deadlock": "Deadlock occurs when a set of activities wait forever for resources held by one another.",
    "scheduling": "Scheduling chooses which ready work receives a processor according to goals such as fairness, throughput, or latency.",
    "file systems": "A file system organizes persistent data into names, metadata, allocation structures, and access operations.",
    "system calls": "A system call is a controlled interface through which a program requests a privileged operating-system service.",
}

ANGLES = [
    ("definition", "What is {concept}, and what problem does it address in {context}?"),
    ("mechanism", "How does {concept} work internally when it is used in {context}?"),
    ("comparison", "How should an engineer compare {concept} with its main alternative in {context}?"),
    ("tradeoff", "What trade-offs should guide the choice of {concept} for {context}?"),
    ("failure", "What common failure does {concept} prevent or expose in {context}, and why?"),
    ("design", "How would you apply {concept} responsibly when designing {context}?"),
    ("diagnosis", "A {context} has a problem related to {concept}; what reasoning steps should diagnose it?"),
    ("testing", "What evidence would demonstrate that {concept} is correctly implemented in {context}?"),
]

@dataclass(frozen=True)
class Question:
    subject: str
    topic: str
    question: str
    answer: str
    expected_concepts: str
    difficulty: str
    question_hash: str


def _definition(concept: str) -> str:
    return DEFINITIONS.get(concept, f"{concept.title()} is a language or system concept that determines how a program represents, processes, or coordinates work.")


def _difficulty(angle: str, index: int) -> str:
    if angle in {"definition", "mechanism"}:
        return "Easy"
    if angle in {"comparison", "testing", "failure"}:
        return "Medium"
    return "Hard" if index % 5 else "Medium"


def _answer(subject: str, concept: str, context: str, angle: str, index: int) -> str:
    definition = _definition(concept)
    sentence_two = {
        "definition": f"In {subject}, its boundary separates the decision about {concept} from unrelated implementation details in {context}.",
        "mechanism": f"The mechanism uses explicit state and invariants, which must remain true while a {context} applies {concept}.",
        "comparison": f"A useful comparison of {concept} examines correctness, complexity, observability, and workload rather than relying on a blanket rule.",
        "tradeoff": f"Choosing {concept} trades resource cost and implementation complexity against the behavior required by {context}.",
        "failure": f"When {concept} fails in {context}, diagnosis begins with the violated invariant and the smallest event that reproduces it.",
        "design": f"A design using {concept} should expose its contract, keep responsibilities narrow, and record assumptions that maintainers can test.",
        "diagnosis": f"To diagnose {concept} in {context}, measure relevant state and reproduce the behavior under controlled conditions before changing code.",
        "testing": f"Tests for {concept} in {context} should cover normal behavior, boundaries, failure handling, and interactions with neighboring components.",
    }[angle]
    sentence_three = f"The {angle} perspective is correct only when {concept} preserves predictable results as {context} changes load, input, or concurrency." 
    sentence_four = f"For example, begin with a small {concept} case, inspect its invariant, and then repeat the check with a representative {context} workload." 
    limitations = [
        f"One limitation is that {concept} can add resource or coordination cost when the workload grows.",
        f"Its boundary is important because {concept} cannot compensate for an incorrect contract elsewhere in the design.",
        f"The guarantee from {concept} is narrower than a general promise about consistency, latency, safety, or maintainability.",
        f"A team should revisit the choice if measurements show that {concept} increases contention or obscures failure handling.",
        f"The result still depends on valid inputs, explicit invariants, and an implementation that respects the {concept} contract.",
    ]
    conclusions = [
        f"For {subject}, the decision is justified when the measured behavior of {concept} matches the stated requirement.",
        f"For {subject}, a reviewer should accept {concept} only after its guarantees are connected to an observable test or operational signal.",
        f"For {subject}, the strongest explanation of {concept} names both the guarantee it provides and the assumption it leaves to the caller.",
        f"In {subject}, {concept} is a tool for a defined constraint, not a substitute for workload analysis or clear ownership.",
        f"The final choice should preserve the {concept} invariant while keeping the {subject} design understandable to its maintainers.",
    ]
    sentence_five = limitations[index % len(limitations)]
    sentence_six = conclusions[(index // len(limitations)) % len(conclusions)]
    return " ".join([definition, sentence_two, sentence_three, sentence_four, sentence_five, sentence_six])


def _hash(question: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", question.lower().strip()).encode()).hexdigest()


def planned_distribution() -> dict[str, int]:
    return TARGETS.copy()


def generate_records(subject: str, target: int) -> list[Question]:
    concepts = CORE_CONCEPTS[subject] if subject in CORE_CONCEPTS else LANGUAGE_CONCEPTS[subject]
    records: list[Question] = []
    combinations = itertools.product(concepts, ANGLES, CONTEXTS)
    for index, (concept, (angle, template), context) in enumerate(combinations):
        if len(records) >= target:
            break
        question = f"In {subject}, {template.format(concept=concept, context=context)}"
        answer = _answer(subject, concept, context, angle, index)
        record = Question(subject, concept, question, answer,
                          ", ".join([concept, subject, angle, "correctness", "trade-offs"]),
                          _difficulty(angle, index), _hash(question))
        records.append(record)
    if len(records) < target:
        raise RuntimeError(f"Catalog cannot produce {target} records for {subject}; only {len(records)} available")
    return records


def ensure_schema(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(SCHEMA.read_text(encoding="utf-8"))


def insert_missing(conn, records: Iterable[Question]) -> int:
    values = [tuple(asdict(record).values()) for record in records]
    with conn.cursor() as cursor:
        execute_values(cursor, """INSERT INTO question_bank
            (subject, topic, question, answer, expected_concepts, difficulty, question_hash)
            VALUES %s ON CONFLICT (question_hash) DO UPDATE SET
                answer = EXCLUDED.answer,
                expected_concepts = EXCLUDED.expected_concepts,
                difficulty = EXCLUDED.difficulty""", values, page_size=200)
        return cursor.rowcount


def generate_to_target() -> dict[str, int]:
    with transaction() as conn:
        ensure_schema(conn)
        inserted: dict[str, int] = {}
        for subject, target in TARGETS.items():
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM question_bank WHERE subject = %s", (subject,))
                existing = cursor.fetchone()[0]
            records = generate_records(subject, target)
            inserted[subject] = insert_missing(conn, records)
            print(f"{subject:<42} target={target:4d} existing={existing:4d} inserted={inserted[subject]:4d}")
        return inserted


if __name__ == "__main__":
    print("Planned distribution:")
    for name, count in TARGETS.items():
        print(f"{name:<42} {count}")
    print("\nGenerating missing records in committed batches...")
    print(json.dumps(generate_to_target(), indent=2))
