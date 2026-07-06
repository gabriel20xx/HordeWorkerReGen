import torch
from loguru import logger

# torch.cuda.get_device_name() raises RuntimeError when no CUDA/ROCm device is visible
# (no GPU, CPU-only box, CUDA_VISIBLE_DEVICES="", DirectML-only). This module is imported
# during hordelib initialisation, so an unguarded query would crash the inference process
# at startup on such machines — fall back to "no AMD GPU" instead.
try:
    _device_name = torch.cuda.get_device_name() if torch.cuda.is_available() else ""
except Exception:
    _device_name = ""

if "AMD" in _device_name or "Radeon" in _device_name:
    try:  # this import is handled via  script, skipping it in mypy. If this fails somehow the module will simply not run.
        from flash_attn import flash_attn_func  # type: ignore

        sdpa = torch.nn.functional.scaled_dot_product_attention

        def sdpa_hijack(
            query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, enable_gqa=False
        ):
            if query.shape[3] <= 256 and attn_mask is None and query.dtype != torch.float32:
                hidden_states = flash_attn_func(
                    q=query.transpose(1, 2),
                    k=key.transpose(1, 2),
                    v=value.transpose(1, 2),
                    dropout_p=dropout_p,
                    causal=is_causal,
                    softmax_scale=scale,
                ).transpose(1, 2)
            else:
                hidden_states = sdpa(
                    query=query,
                    key=key,
                    value=value,
                    attn_mask=attn_mask,
                    dropout_p=dropout_p,
                    is_causal=is_causal,
                    scale=scale,
                    enable_gqa=enable_gqa,
                )
            return hidden_states

        torch.nn.functional.scaled_dot_product_attention = sdpa_hijack
        logger.debug("# # # AMD GO FAST # # #")
    except ImportError as e:
        logger.debug(f"# # # AMD GO SLOW {e} # # #")
else:
    logger.debug(f"# # # AMD GO SLOW Could not detect AMD GPU from: {_device_name!r} # # #")
