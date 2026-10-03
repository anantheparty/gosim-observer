"""Small public-only policy genome; research scaffold, not a submission agent.

There is no scorer/Scenario access in this module. Caller-derived booleans are
public information. Tree terminals name target-independent package operators.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Union

PREDICATES = ("request_surplus", "required_scarce", "feedback_drop", "resynced")
OPERATORS = ("native", "request_bundle", "scarce_required")


@dataclass(frozen=True)
class PublicFeatures:
    request_surplus: bool
    required_scarce: bool
    feedback_drop: bool
    resynced: bool


@dataclass(frozen=True)
class Leaf:
    operator: str

    def __post_init__(self):
        if self.operator not in OPERATORS:
            raise ValueError(self.operator)


@dataclass(frozen=True)
class Branch:
    predicate: str
    yes: "Tree"
    no: "Tree"

    def __post_init__(self):
        if self.predicate not in PREDICATES:
            raise ValueError(self.predicate)


Tree = Union[Leaf, Branch]


def decide(tree: Tree, public: PublicFeatures) -> str:
    while isinstance(tree, Branch):
        tree = tree.yes if getattr(public, tree.predicate) else tree.no
    return tree.operator


def phenotype(tree: Tree) -> tuple[str, ...]:
    """Exact behavior on the declared four-boolean abstraction (all 16 states).

    This is not equivalence over the full GOSIM state; it is exact only because
    this genome's decisions cannot inspect any other field.
    """
    return tuple(decide(tree, PublicFeatures(*bits))
                 for bits in product((False, True), repeat=len(PREDICATES)))


def reduce_tree(tree: Tree) -> Tree:
    if isinstance(tree, Leaf):
        return tree
    yes, no = reduce_tree(tree.yes), reduce_tree(tree.no)
    if phenotype(yes) == phenotype(no):
        return min((yes, no), key=lambda child: (nodes(child), repr(child)))
    return Branch(tree.predicate, yes, no)


def nodes(tree: Tree) -> int:
    return 1 if isinstance(tree, Leaf) else 1 + nodes(tree.yes) + nodes(tree.no)


def stumps() -> list[Tree]:
    leaves = [Leaf(operator) for operator in OPERATORS]
    return leaves + [Branch(predicate, yes, no)
                     for predicate in PREDICATES for yes in leaves for no in leaves]
