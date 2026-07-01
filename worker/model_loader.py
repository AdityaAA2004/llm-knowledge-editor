import logging
import os

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None

# Ordered list of LEACE ConceptScrubbers currently attached (via permanent forward
# hooks) to `_model`. Erasure is cumulative, so this grows with each erase job and is
# saved into every checkpoint sidecar so the erasure carries across edits and rollbacks.
_active_scrubbers: list = []


def load_model():
    global _model, _tokenizer

    model_id = os.environ["MODEL_ID"]
    weights_path = os.environ["MODEL_WEIGHTS_PATH"]
    hf_token = os.environ.get("HF_TOKEN")

    logger.info("Downloading/verifying weights for %s → %s", model_id, weights_path)
    snapshot_download(
        repo_id=model_id,
        local_dir=weights_path,
        token=hf_token,
        ignore_patterns=["*.msgpack", "*.h5", "flax_model*", "rust_model*"],
    )

    logger.info("Loading tokenizer...")
    _tokenizer = AutoTokenizer.from_pretrained(weights_path)
    if _tokenizer.pad_token is None:
        _tokenizer.pad_token = _tokenizer.eos_token

    logger.info("Loading model to GPU (fp16, device_map=auto)...")
    _model = AutoModelForCausalLM.from_pretrained(
        weights_path,
        torch_dtype=torch.float16,
        device_map="auto",
        low_cpu_mem_usage=True,
    )
    _model.eval()

    device = next(_model.parameters()).device
    logger.info("Model ready: %s on %s", model_id, device)
    return _model, _tokenizer


def get_model():
    if _model is None or _tokenizer is None:
        raise RuntimeError("Model not loaded — load_model() must be called at worker startup")
    return _model, _tokenizer
