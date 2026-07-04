"""Canonical, ordered stage lists per job type — the single source of truth.

The `key`s here are the contract the worker emits `job_stage_log` rows against
(see worker/stage_log.py and the task instrumentation). The backend folds the
raw event rows onto these stages in GET /jobs/{id}/stages. Deep sub-events from
the vendored compute_* patches are emitted as PROGRESS rows keyed to `apply_edit`,
so they nest under that stage rather than needing their own canonical entries.
"""

from app.models.job import JobType

# ordered list of (stage_key, label) per job_type
JOB_STAGES: dict[str, list[tuple[str, str]]] = {
    JobType.edit_rome.value: [
        ("load_triples", "Load triples"),
        ("build_requests", "Build edit requests"),
        ("apply_edit", "Compute ROME edit"),
        ("save_checkpoint", "Save checkpoint"),
        ("finalize", "Commit to database"),
    ],
    JobType.edit_memit.value: [
        ("load_triples", "Load triples"),
        ("build_requests", "Build edit requests"),
        ("apply_edit", "Compute MEMIT batch"),
        ("save_checkpoint", "Save checkpoint"),
        ("finalize", "Commit to database"),
    ],
    JobType.erase_elm.value: [
        ("load_triples", "Load triples"),
        ("build_dataset", "Build erasure dataset"),
        ("fit_scrubber", "Fit LEACE erasers"),
        ("apply_scrubber", "Attach scrubber"),
        ("save_checkpoint", "Save checkpoint"),
        ("finalize", "Commit to database"),
    ],
    JobType.rollback.value: [
        ("locate_checkpoint", "Locate checkpoint"),
        ("load_weights", "Load checkpoint weights"),
        ("attach_scrubbers", "Re-attach scrubbers"),
        ("swap_model", "Swap active model"),
        ("reconcile_db", "Reconcile triple state"),
        ("finalize", "Commit to database"),
    ],
}


def stages_for(job_type: str) -> list[tuple[str, str]]:
    return JOB_STAGES.get(job_type, [])
