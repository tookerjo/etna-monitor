# Build constraints

Read SPEC.md first. It is the source of truth. Where this file and the spec
disagree, the spec wins on behaviour and this file wins on how to build.

## Stack

Python 3.11. Standard library plus `requests` and `PyYAML` only. No pandas, no
numpy, no ORM, no framework. If a dependency seems necessary, write it in the
commit message why, and prefer the standard library.

Tests with `pytest`. No network access in tests. Every external call is behind
a function that tests replace with a fixture.

## Verify before you write

Three external services are involved. For each one, before writing its client
module, make one real request and record the actual response shape in a
comment at the top of the module. Do not write a client against assumed
parameter names or an assumed response format.

If a service does not behave as the spec describes, stop and write the
discrepancy into `NOTES.md` rather than working around it silently.

Identify the client honestly in the User-Agent header on every request. INGV
and NASA both publish services for public use and both deserve a real
identifier and reasonable request volume. One request per source per run.

## Order of work

1. `state.py` and its tests. Nothing else works without correct state.
2. `thresholds.py` and its tests. Pure functions over lists of numbers, no I/O.
3. One source module at a time, each with its failure-path test.
4. `notify.py`.
5. `run.py` wiring it together.
6. The workflow file.
7. README last, describing what was actually built.

Commit after each numbered step, with tests passing. Do not batch the work into
one commit at the end.

## Rules

Threshold logic contains no I/O and no clock reads. Time is passed in. This is
what makes it testable.

A source failure is never silent. Log it, mark the source unavailable in the
run record, and continue. Never return an empty list to mean both "no events"
and "the call failed".

No secret is ever written to a file in the repository, printed to a log, or
included in a commit. Secrets come from environment variables.

No function in this codebase produces a prediction, a probability of future
activity, or a risk score. The system reports observations and changes in
observations.

Write the config file with the threshold values from the spec as defaults, and
comment each one as unvalidated.

## Subagents

If work is fanned out, subagents implement modules against interfaces that
already exist and have tests. A subagent may not create a new module, change a
shared interface, add a dependency, or edit `config.yaml` schema. If a subagent
needs any of those, it stops and reports.

## Budget

Stop and report if the build exceeds the wall-clock or spend cap set at
invocation. Report what is done and what is not rather than continuing.

## Definition of done

Every numbered item in the spec's acceptance criteria has been executed, not
inspected. Write the actual command output for each into `ACCEPTANCE.md`. An
untested claim of completion is a failure of the build.
