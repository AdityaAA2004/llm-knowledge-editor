"""Checkpoint disk-retention policy shared by edit and erase tasks.

Each checkpoint is a full ~6-7GB copy of the model on the 50GB `/data` network volume,
and nothing else ever reclaims that space. Left unbounded, the volume fills up and
checkpoint saves start failing with ENOSPC mid-write — which is what happened on
2026-07-05 (see edit_job rows around 22:39-23:02 UTC) and, combined with the in-place
edit bug fixed in edit_tasks.py/erase_tasks.py, corrupted the model.
"""

import logging
import os
import shutil

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Keep this many most-recent checkpoints on disk (plus whichever one is active, in case
# it's older than the window) so rollback still has recent history without exhausting
# the volume. Older DB rows are kept for audit history; only their directory is pruned.
CHECKPOINT_RETENTION = 3


def prune_old_checkpoints(db: Session, keep: int = CHECKPOINT_RETENTION) -> None:
    rows = db.execute(
        text("SELECT path, is_active FROM model_checkpoint ORDER BY created_at DESC")
    ).fetchall()

    keep_paths = {path for path, _is_active in rows[:keep]}
    keep_paths |= {path for path, is_active in rows if is_active}

    for path, _is_active in rows[keep:]:
        if path in keep_paths or not os.path.isdir(path):
            continue
        try:
            shutil.rmtree(path)
            logger.info("Pruned old checkpoint directory %s", path)
        except OSError:
            logger.warning("Failed to prune checkpoint directory %s", path, exc_info=True)
