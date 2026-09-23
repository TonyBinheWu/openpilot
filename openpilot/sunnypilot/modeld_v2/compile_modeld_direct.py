#!/usr/bin/env python3
"""
Compile a sunnypilot supercombo big model using the existing split warp/policy
runtime path instead of the legacy unified run_model packed-frame JIT.

The resulting PKL intentionally does not contain a ``run_model`` entry.
modeld_v2 therefore selects its existing direct VisionIPC frame path:
VisionBuf -> Tensor.from_blob() -> warp -> run_policy.

This keeps legacy PKLs fully compatible while allowing newly compiled Chestnut
models to avoid the per-frame np.copyto() staging used by unified run_model.
"""

import argparse
import os
from functools import partial

os.environ['GMMU'] = '0'

import openpilot.selfdrive.modeld.compile_modeld as stock
from openpilot.common.file_chunker import chunk_file, get_chunk_targets
from openpilot.selfdrive.modeld.get_model_metadata import make_metadata_dict
from openpilot.selfdrive.modeld.helpers import dump_oob
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
from openpilot.sunnypilot.modeld_v2.compile_modeld import (
  POLICY_INPUTS,
  WARP_INPUTS,
  _parse_size,
  compile_jit,
  derive_frame_skip,
  make_random_images,
  make_supercombo_input_queues,
  make_warp_queues,
  read_file_chunked_to_disk,
)
from tinygrad.device import Device
from tinygrad.engine.jit import TinyJit
from tinygrad.nn.onnx import OnnxRunner


def compile_direct_supercombo(args: argparse.Namespace) -> None:
  model_path = read_file_chunked_to_disk(args.supercombo_onnx)
  model_w, model_h = args.model_size

  metadata = make_metadata_dict(model_path)
  frame_skip = args.frame_skip or derive_frame_skip({}, metadata['input_shapes'])
  runner = OnnxRunner(model_path)

  # Keep the same metadata shape modeld_v2 expects for a supercombo model, but
  # advertise the device used by the independently compiled warp JIT.
  output_data = {
    'metadata': {
      'model': metadata,
      **metadata,
      'warp_dev': Device.DEFAULT,
    },
    'input_devices': {'model': Device.DEFAULT},
  }

  # Compile policy independently. This is the same policy function used by the
  # unified compiler; only the camera-frame ingestion boundary is separated.
  run_policy = stock.make_run_policy(runner, metadata, frame_skip)
  policy_jit = TinyJit(run_policy, prune=True)
  make_policy_queues = partial(make_supercombo_input_queues, metadata['input_shapes'], frame_skip)
  make_random_policy_inputs = partial(
    make_random_images,
    keys=['warped'],
    shape=(2, 6, model_h // 2, model_w // 2),
    device=Device.DEFAULT,
  )

  print(f"Compiling direct-frame run_policy JIT (model_size={model_w}x{model_h}, frame_skip={frame_skip})...")
  output_data['run_policy'] = compile_jit(
    policy_jit,
    POLICY_INPUTS,
    make_policy_queues,
    make_random_inputs=make_random_policy_inputs,
    benchmark_runs=args.benchmark_runs,
  )

  # Compile one camera warp JIT per supported camera resolution. At runtime
  # modeld_v2 feeds these JITs Tensor.from_blob() views of the VisionIPC NV12
  # buffers instead of first copying both frames into packed_npy_inputs.
  for cam_w, cam_h in args.camera_resolutions:
    print(f"Compiling direct-frame warp JIT for {cam_w}x{cam_h}...")
    nv12 = stock.NV12Frame(cam_w, cam_h, *get_nv12_info(cam_w, cam_h))
    frame_copy_size = stock.nv12_copy_size(nv12.stride, nv12.y_height, nv12.uv_height)
    make_random_warp_inputs = partial(
      make_random_images,
      keys=['frame', 'big_frame'],
      shape=frame_copy_size,
      device=Device.DEFAULT,
    )
    warp_jit = TinyJit(stock.make_warp(nv12, model_w, model_h), prune=True)
    output_data[(cam_w, cam_h)] = compile_jit(
      warp_jit,
      WARP_INPUTS,
      make_warp_queues,
      make_random_inputs=make_random_warp_inputs,
      benchmark_runs=args.benchmark_runs,
    )

  with open(args.output, 'wb') as f:
    dump_oob(output_data, f)

  pkl_size = os.path.getsize(args.output)
  print(f"Saved direct-frame JIT to {args.output} ({pkl_size / 1e6:.2f} MB)")
  chunk_targets = get_chunk_targets(args.output, pkl_size)
  chunk_file(args.output, chunk_targets)
  print(f"Chunked into {len(chunk_targets) - 1} file(s)")


if __name__ == '__main__':
  parser = argparse.ArgumentParser(
    description='Compile a direct-frame sunnypilot supercombo/Chestnut model PKL',
  )
  parser.add_argument('--model-size', type=_parse_size, required=True, help='model input WxH')
  parser.add_argument('--camera-resolutions', type=_parse_size, nargs='+', required=True)
  parser.add_argument('--frame-skip', type=int, default=None, help='frame skip value (auto-derived if omitted)')
  parser.add_argument('--benchmark-runs', type=int, default=1)
  parser.add_argument('--supercombo-onnx', required=True)
  parser.add_argument('--output', required=True)
  compile_direct_supercombo(parser.parse_args())
