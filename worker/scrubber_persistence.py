"""Persist and re-attach LEACE concept-erasure scrubbers as a checkpoint sidecar.

`concept_erasure.ConceptScrubber` applies its per-layer `LeaceEraser`s only inside a
`with scrubber.scrub(model): ...` context — the hooks are removed on exit. For our
platform the erasure must persist as part of the model artifact, so we:

  1. save the fitted erasers next to a normal HF weight checkpoint (`scrubber.pt`), and
  2. re-attach them as *permanent* forward hooks whenever that checkpoint is loaded
     (erase completion and rollback).

Erasure is *cumulative*: a second erase job fits its erasers on activations that already
have the first job's erasers applied, so the two must both stay attached, in fit order.
We therefore persist an ordered *list* of scrubbers and re-apply them in sequence (hook
execution order on a module follows registration order, matching the fit order).

The registration below mirrors `ConceptScrubber.apply_hook` verbatim (same norm-layer
filter, same `mangle_module_path` keys, same pre/post-hook semantics) but never calls
`handle.remove()`, so the erasure lives for the lifetime of the model in memory.
"""

import os
import logging
from functools import partial

import torch

logger = logging.getLogger(__name__)

SCRUBBER_FILENAME = "scrubber.pt"


def save_scrubbers(scrubbers: list, checkpoint_path: str) -> str:
    """Serialize an ordered list of ConceptScrubbers into the checkpoint dir."""
    path = os.path.join(checkpoint_path, SCRUBBER_FILENAME)
    payload = [{"erasers": s.erasers, "pre_hook": s.pre_hook} for s in scrubbers]
    torch.save(payload, path)
    return path


def load_scrubbers(checkpoint_path: str) -> list:
    """Reconstruct the ordered list of ConceptScrubbers from a sidecar (or [] if absent)."""
    path = os.path.join(checkpoint_path, SCRUBBER_FILENAME)
    if not os.path.exists(path):
        return []

    from concept_erasure import ConceptScrubber

    payload = torch.load(path, map_location="cpu")
    scrubbers = []
    for state in payload:
        scrubber = ConceptScrubber(pre_hook=state["pre_hook"])
        scrubber.erasers = state["erasers"]
        scrubbers.append(scrubber)
    return scrubbers


def apply_scrubber(model, scrubber) -> list:
    """Permanently register one scrubber's erasers as forward hooks on `model`.

    Returns the list of hook handles. Erasers are moved to the model's device and the
    matmul runs in the eraser's own dtype (result cast back via `type_as`) so it stays
    correct on an fp16 model even though the erasers were fit in fp32.
    """
    from transformers import PreTrainedModel
    from concept_erasure import LeaceEraser
    from concept_erasure.utils import assert_type, is_norm_layer, mangle_module_path

    target = model.base_model if isinstance(model, PreTrainedModel) else model
    device = next(target.parameters()).device

    # Move erasers onto the model's device once so hook matmuls don't cross devices.
    scrubber.erasers = {k: e.to(device) for k, e in scrubber.erasers.items()}

    def post_wrapper(_, __, output, name):
        eraser = assert_type(LeaceEraser, scrubber.erasers[mangle_module_path(name)])
        return eraser(output.to(eraser.proj_left.dtype)).type_as(output)

    def pre_wrapper(_, inputs, name):
        x, *extras = inputs
        eraser = assert_type(LeaceEraser, scrubber.erasers[mangle_module_path(name)])
        return (eraser(x.to(eraser.proj_left.dtype)).type_as(x), *extras)

    handles = []
    for name, mod in target.named_modules():
        if is_norm_layer(mod) and mangle_module_path(name) in scrubber.erasers:
            if scrubber.pre_hook:
                handles.append(mod.register_forward_pre_hook(partial(pre_wrapper, name=name)))
            else:
                handles.append(mod.register_forward_hook(partial(post_wrapper, name=name)))

    if len(handles) != len(scrubber.erasers):
        logger.warning(
            "Applied %d/%d erasers — some module paths did not match the model",
            len(handles), len(scrubber.erasers),
        )
    return handles


def apply_scrubbers(model, scrubbers: list) -> list:
    """Apply an ordered list of scrubbers to a model, preserving fit order."""
    handles = []
    for scrubber in scrubbers:
        handles.extend(apply_scrubber(model, scrubber))
    return handles
