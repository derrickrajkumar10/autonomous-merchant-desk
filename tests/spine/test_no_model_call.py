"""No language model participates in checks 1 to 4. Asserted, not promised.

This is the claim the whole design rests on and the one that will be made on camera:
cryptography decides whether a signature is valid, a model never does (CONTEXT.md
section 5, principle 1). It is also the claim a well-meaning refactor breaks silently --
somebody adds a "smarter" mandate reader six months from now and nothing fails, because
every other test in this suite is about *outcomes*, and a model that agreed with the
cryptography would produce identical ones.

So it is tested two ways, and neither is a search for the word "model" in a comment.

**What the code may import.** Every module the spine reaches is parsed and its imports
are compared against a closed list. Nothing on that list can talk to a model, or to a
network at all: there is no HTTP client on it. An SDK added to ``desk/`` would have to
be added here too, in a diff a reviewer would notice.

**What running one costs.** A full request is driven through the spine while watching
which modules Python loads. A model call has to import something to make it, and
nothing new appears.

Check 5 lives outside all of this. When it arrives it will have its own package, its own
model SDK, and it will not be in ``SPINE``.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import desk
from desk.identity import AgentIdentity
from desk.spine import TrustSpine
from tests.spine.conftest import a_request
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: The packages checks 1 to 4 are made of, plus the trail they all write to.
SPINE = ("audit", "identity", "mandate", "spend", "freshness", "spine")

#: Packages under ``desk/`` that are deliberately *not* part of checks 1 to 4, each with
#: the reason it is out. Being on this list is not permission to call a model -- it means
#: this file makes no claim either way, and the claim CONTEXT.md section 5 makes is about
#: the spine.
#:
#: - ``catalogue`` -- costs, prices and margin arithmetic (ticket 07). It runs *after*
#:   the spine has finished, on a request the four checks already accepted, and it
#:   decides what a deal is worth rather than whether it is allowed.
#: - ``negotiation`` -- levers, the fixed policy and the closed mandate (ticket 08). It
#:   runs after the spine too, and its own suite asserts the property that matters here:
#:   nothing it does is probabilistic either. Ticket 21 makes the lever choice learned,
#:   at which point that stops being true of one object inside it -- which is exactly why
#:   the choice sits behind a substitutable one, and why this package is not on the list
#:   above.
#: - ``settlement`` -- the charge, the receipt and the receipt store (ticket 09). Also
#:   after the spine, and the furthest thing from it: it calls a *third party* over the
#:   network, which is the one dependency no check may have. A spine module importing it
#:   would put a payment rail's availability in the path of deciding whether a mandate
#:   is valid, so the test below is what keeps that from happening quietly.
NOT_THE_SPINE = ("catalogue", "negotiation", "settlement")

#: Found through the installed package rather than through the working directory, so
#: that this reads the ``desk`` the tests actually import.
DESK = pathlib.Path(desk.__file__).parent

#: Everything the deterministic spine is allowed to import. Three third-party names --
#: a Postgres driver, a JWS library and the cryptography it is built on -- and the
#: standard library modules beside them. No HTTP client, no model SDK, and nothing that
#: could acquire one indirectly.
PERMITTED = frozenset(
    {
        "__future__",
        "collections",
        "contextlib",
        "cryptography",
        "dataclasses",
        "datetime",
        "decimal",
        "desk",
        "enum",
        "hashlib",
        "json",
        "jwt",
        "os",
        "psycopg",
        "psycopg_pool",
        "re",
        # Salt for an SD-JWT disclosure. The one source of randomness the mandate
        # library holds, and it goes into a digest rather than into a decision.
        "secrets",
        "typing",
    }
)

#: What a model call would have to load. Names rather than a network guard, because the
#: spine talks to Postgres over a socket and a guard that banned sockets outright would
#: be a guard against the database.
MODEL_SDKS = (
    "anthropic",
    "openai",
    "google",
    "litellm",
    "langchain",
    "langgraph",
    "transformers",
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "http",
)


def test_no_module_in_the_spine_imports_anything_that_could_call_a_model() -> None:
    """Read the imports of every module checks 1 to 4 are built from."""
    offending = {
        f"{module.relative_to(DESK)}: {root}"
        for module in _spine_modules()
        for root in _imported_roots(module)
        if root not in PERMITTED
    }

    assert not offending, (
        f"the deterministic spine imported something outside its closed list: "
        f"{sorted(offending)}. If this is a genuine new dependency, adding it here is "
        f"the deliberate act; if it can reach a model, checks 1 to 4 are not "
        f"deterministic any more and the claim in CONTEXT.md section 5 has stopped "
        f"being true."
    )


def test_no_module_in_the_spine_reaches_into_a_package_outside_it() -> None:
    """The hole ``PERMITTED`` cannot see, because ``desk`` is on it.

    The test above compares *top-level* import roots, so ``from desk.catalogue import
    Product`` inside a check reads as the root ``desk`` and passes. That is fine while
    every package under ``desk/`` is deterministic, and it stops being fine the moment
    one is not: check 5 will live under ``desk/`` too, and a spine module importing it
    would be the exact thing this file exists to prevent, waved through by a root name.

    So the spine's reach into its own project is checked at the *package* level.
    Relative imports are resolved rather than skipped, since ``from ..inspector import
    ...`` is the same reach spelled differently.
    """
    outside = {
        f"{module.relative_to(DESK)}: desk.{package}"
        for module in _spine_modules()
        for package in _desk_packages_imported(module)
        if package not in SPINE
    }

    assert not outside, (
        f"a module in checks 1 to 4 imported from a package outside the spine: "
        f"{sorted(outside)}. Everything the spine depends on has to be deterministic, "
        f"and a package on NOT_THE_SPINE carries no such promise."
    )


def test_running_a_whole_request_through_the_spine_loads_no_model_sdk(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The import list, from the other side: what one real request actually loads.

    Both a request that passes and one that is refused, since a refusal is exactly where
    a future "let the model take a second look" would be tempting to add.
    """
    before = set(sys.modules)

    assert spine.receive(a_request(wallet, agent, identity)).passed
    assert not spine.receive(a_request(wallet, agent, identity, item_id="SKU-NOT-YOURS")).passed

    loaded = {name.split(".")[0] for name in set(sys.modules) - before}
    assert not loaded & set(MODEL_SDKS), f"the spine loaded {sorted(loaded)} while running"


def test_the_spine_packages_are_the_ones_this_file_thinks_they_are() -> None:
    """A guard on the guard: a new package under ``desk/`` is either in ``SPINE`` or not.

    Without this, adding ``desk/inspector/`` and forgetting to think about it would leave
    the two tests above quietly passing over a smaller and smaller part of the Desk. So
    a new package fails this test until somebody has said, in writing, which side of the
    spine it is on.
    """
    packages = {path.name for path in DESK.iterdir() if path.is_dir()}

    assert packages - {"__pycache__"} == set(SPINE) | set(NOT_THE_SPINE), (
        "desk/ has gained or lost a package. If it is part of checks 1 to 4, add it to "
        "SPINE; if it is not, add it to NOT_THE_SPINE with the reason -- and either way "
        "say which in this test."
    )


def _spine_modules() -> list[pathlib.Path]:
    modules = [module for package in SPINE for module in (DESK / package).rglob("*.py")]
    assert modules, f"found no modules to read under {DESK}"
    return modules


def _imported_roots(module: pathlib.Path) -> set[str]:
    """The top-level name of everything this module imports, however it imports it."""
    return {name.split(".")[0] for name in _imported_names(module)}


def _desk_packages_imported(module: pathlib.Path) -> set[str]:
    """The packages under ``desk/`` this module reaches into, ``desk.spend`` as ``spend``."""
    return {
        name.split(".")[1]
        for name in _imported_names(module)
        if name.split(".")[0] == "desk" and len(name.split(".")) > 1
    }


def _imported_names(module: pathlib.Path) -> set[str]:
    """Every dotted name this module imports, with relative imports resolved.

    A relative import is the same reach as an absolute one and has to be read as one,
    so ``from ..catalogue import Product`` in ``desk/spend/check.py`` comes back as
    ``desk.catalogue`` rather than being skipped for having no module root.
    """
    package = (DESK.parent / module.relative_to(DESK.parent)).parent.relative_to(DESK.parent)
    parts = ["desk", *package.parts[1:]]

    names: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    names.add(node.module)
            else:
                base = parts[: len(parts) - node.level + 1]
                names.add(".".join([*base, *([node.module] if node.module else [])]))
    return names
